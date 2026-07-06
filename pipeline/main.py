"""
main.py — CLI entry point for running the pipeline end-to-end.

Usage:
    # Full mock run (no API key needed):
    python main.py --rubric examples/rubric.json --pdf examples/sample_exam.pdf --mock

    # Real Gemini run:
    python main.py --rubric examples/rubric.json --pdf path/to/exam.pdf

    # Auto-approve all students (no interactive prompts):
    python main.py --rubric examples/rubric.json --pdf exam.pdf --mock --auto-approve

The CLI simulates the TA review loop interactively — in production,
the FastAPI server handles decisions from the GradeOps dashboard instead.
"""

from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path

from langgraph.types import Command


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="GradeOps grading pipeline CLI")
    p.add_argument("--rubric",       required=True, help="Path to rubric JSON file")
    p.add_argument("--pdf",          required=True, help="Path to exam PDF")
    p.add_argument("--exam-id",      default=None,  help="Optional exam ID (auto-generated if omitted)")
    p.add_argument("--auto-approve", action="store_true", help="Approve all AI grades without prompting")
    return p.parse_args()


def _interactive_review(interrupt_payload: dict) -> str | dict:
    """Prompt the CLI user for a TA decision."""
    sid     = interrupt_payload["student_id"]
    grade   = interrupt_payload.get("grade", {})
    q_grades = grade.get("question_grades", [])

    print("\n" + "─" * 60)
    print(f"  Student: {sid}")
    print(f"  OCR confidence: {interrupt_payload.get('ocr_confidence', '?'):.0%}")

    if interrupt_payload.get("needs_priority_review"):
        print("  ⚠  PRIORITY: Low OCR confidence — review carefully")

    if interrupt_payload.get("plagiarism_score"):
        print(f"  ⚠  PLAGIARISM: {interrupt_payload['plagiarism_score']:.0%} match with {interrupt_payload['plagiarism_match']}")

    print("\n  Transcript (first 300 chars):")
    transcript = interrupt_payload.get("transcript", "")
    print(f"  {transcript[:300]}{'…' if len(transcript) > 300 else ''}")

    print("\n  AI Grades:")
    for qg in q_grades:
        print(f"    {qg['question_id']}: {qg['score']}/{qg['max_score']} — {qg['justification'][:80]}…")

    total = sum(qg["score"] for qg in q_grades)
    max_t = sum(qg["max_score"] for qg in q_grades)
    print(f"\n  Total AI score: {total}/{max_t}")
    print("─" * 60)
    print("  [A] Approve  [O] Override  [E] Escalate  [S] Skip (approve)")

    while True:
        choice = input("  Decision: ").strip().lower()
        if choice in ("a", "s", ""):
            return "approve"
        elif choice == "o":
            try:
                new_score = float(input(f"  New score (0–{max_t}): ").strip())
                comment   = input("  Comment: ").strip()
                return {"action": "override", "score": new_score, "comment": comment}
            except ValueError:
                print("  Invalid score — try again.")
        elif choice == "e":
            return "escalate"
        else:
            print("  Type A, O, E, or S.")


def run_pipeline(rubric_path: str, pdf_path: str, exam_id: str | None, auto_approve: bool):
    """Run the full graph, handling HITL interrupts in the CLI."""
    from pipeline.graph import graph
    from langgraph.types import Command
    from langgraph.errors import GraphInterrupt

    rubric_raw = Path(rubric_path).read_text()
    thread_id  = exam_id or f"cli_{Path(pdf_path).stem}"
    config     = {"configurable": {"thread_id": thread_id}}

    initial_state = {
        "_pdf_path":   pdf_path,
        "_rubric_raw": rubric_raw,
        "exam_id":     exam_id or "",
        "students":    [],
        "current_review_idx": 0,
        "stats":  {},
        "error":  None,
        "rubric": {},
    }

    print(f"\n[pipeline] Starting — exam: {thread_id}")
    print(f"[pipeline] Rubric:   {rubric_path}")
    print(f"[pipeline] PDF:      {pdf_path}")

    # Stream events from the graph; collect the final state
    last_state = {}
    input_val  = initial_state  # first call uses the initial state dict

    while True:
        interrupt_payload = None

        try:
            for event in graph.stream(input_val, config=config, stream_mode="values"):
                last_state = event
                if last_state.get("error"):
                    print(f"\n[pipeline] ERROR: {last_state['error']}")
                    sys.exit(1)
        except GraphInterrupt as exc:
            # LangGraph raises GraphInterrupt when interrupt() is called
            interrupt_payload = exc.args[0][0].value if exc.args else None

        if interrupt_payload is None:
            # Check via get_state for pending interrupts (some LG versions don't raise)
            snapshot = graph.get_state(config)
            for task in snapshot.tasks:
                if task.interrupts:
                    interrupt_payload = task.interrupts[0].value
                    break

        if interrupt_payload is None:
            break  # Graph has completed normally

        if auto_approve:
            decision = "approve"
            sid = interrupt_payload.get("student_id", "?")
            print(f"[pipeline] Auto-approving: {sid}")
        else:
            decision = _interactive_review(interrupt_payload)

        # Resume graph with TA decision
        input_val = Command(resume=decision)

    # Print final stats
    stats = last_state.get("stats", {})
    print("\n" + "═" * 60)
    print("  FINAL GRADE REPORT")
    print("═" * 60)
    print(json.dumps(stats, indent=2))
    exam_out = last_state.get("exam_id") or thread_id
    print(f"\n  Gradebook: scratch/{exam_out}/gradebook.json")



def main():
    args = parse_args()

    run_pipeline(
        rubric_path=args.rubric,
        pdf_path=args.pdf,
        exam_id=args.exam_id,
        auto_approve=args.auto_approve,
    )


if __name__ == "__main__":
    main()
