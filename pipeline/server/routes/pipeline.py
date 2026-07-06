"""
server/routes/pipeline.py — Pipeline management endpoints.

POST /pipeline/start              → upload PDF + rubric, start grading in background
GET  /pipeline/{id}               → poll current state (students, stats, next interrupt)
GET  /pipeline/{id}/export/csv    → download gradebook as CSV
GET  /pipeline/{id}/export/json   → download raw gradebook JSON
"""

from __future__ import annotations
import asyncio
import csv
import io
import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile, Depends
from fastapi.responses import StreamingResponse, Response

from pipeline.config import settings
from pipeline.graph import graph
from pipeline.server.routes.metadata import register_exam, ExamMetadata, verify_course_membership
from pipeline.server.db import get_db
from pipeline.server.routes.auth import check_role, UserOut, get_current_user
from pipeline.tools.storage import get_storage

router = APIRouter(prefix="/pipeline", tags=["pipeline"])

# Thread pool for running the synchronous LangGraph graph without blocking FastAPI
_executor = ThreadPoolExecutor(max_workers=4)


def _config(exam_id: str) -> dict:
    return {"configurable": {"thread_id": exam_id}}


async def _update_exam_status(exam_id: str, status: str, error: str = None):
    db = get_db()
    update_data = {"status": status}
    if error:
        update_data["error"] = error
    await db.exams.update_one({"id": exam_id}, {"$set": update_data})


async def resume_active_pipelines():
    """
    Find all exams marked as 'processing' in MongoDB and resume them.
    This should be called once when the FastAPI server starts.
    """
    db = get_db()
    cursor = db.exams.find({"status": "processing"})
    async for exam in cursor:
        eid = exam["id"]
        print(f"[pipeline] Resuming in-progress exam: {eid}")
        # To resume, we just need to call invoke with None (it will pull from checkpoint)
        # We run it in the background thread pool.
        loop = asyncio.get_event_loop()
        loop.run_in_executor(_executor, graph.invoke, None, _config(eid))


def _run_graph_sync(initial_state: dict, exam_id: str):
    """
    Run graph.invoke() synchronously in a thread-pool worker.
    """
    try:
        # Initial status set by caller
        graph.invoke(initial_state, config=_config(exam_id))
        # Final status is set by the 'finalize' node in the graph
    except Exception as exc:
        print(f"[pipeline] Unhandled error for {exam_id}: {exc}")
        # Note: We can't easily await async _update_exam_status here in a sync thread
        # but the checkpointer will have saved the error if it was a graph error.


def _resume_graph_sync(resume_cmd, exam_id: str):
    """
    Run graph.invoke() synchronously with a resume Command in a thread-pool worker.
    """
    try:
        graph.invoke(resume_cmd, config=_config(exam_id))
    except Exception as exc:
        print(f"[pipeline] Unhandled error resuming {exam_id}: {exc}")


@router.post("/start")
async def start_pipeline(
    pdf:        UploadFile = File(...,           description="Scanned exam PDF"),
    rubric:     UploadFile | None = File(None,   description="Grading rubric JSON"),
    rubric_id:  str | None = Form(default=None,  description="ID of a saved rubric"),
    course_id:  str | None = Form(default=None,  description="Course ID to associate"),
    exam_id:    str | None = Form(default=None,  description="Optional exam ID"),
    name:       str | None = Form(default=None,  description="Custom name for the exam"),
    current_user: UserOut = Depends(check_role("instructor")),
):
    if not course_id:
        raise HTTPException(status_code=400, detail="course_id is required to start a grading pipeline")
    await verify_course_membership(course_id, current_user.id, required_role="instructor")
    """
    Upload a PDF and kick off the grading pipeline.

    If rubric_id is provided, it uses a saved rubric from /metadata/rubrics.
    Otherwise, a new rubric file must be uploaded.
    """
    eid = exam_id or f"exam_{uuid.uuid4().hex[:8]}"
    exam_name = name or f"Exam {eid[-8:]}"
    storage = get_storage()

    # ── Load Rubric ───────────────────────────────────────────────────────────
    if rubric_id:
        db = get_db()
        rubric_doc = await db.rubrics.find_one({"id": rubric_id})
        if not rubric_doc:
            raise HTTPException(status_code=404, detail=f"Rubric {rubric_id} not found in database")
        rubric_raw = rubric_doc.get("rubric_json")
        if not rubric_raw:
            raise HTTPException(status_code=500, detail="Rubric found but contains no data")
    elif rubric:
        rubric_raw = (await rubric.read()).decode(errors='replace')
    else:
        raise HTTPException(status_code=400, detail="Either rubric file or rubric_id is required")

    # ── Save uploaded PDF ─────────────────────────────────────────────────────
    import tempfile
    
    pdf_bytes = await pdf.read()
    
    # Use /tmp for serverless compatibility during PDF splitting
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(pdf_bytes)
        temp_pdf_path = tmp.name
        
    # Still write to our official storage (GridFS)
    pdf_storage_path = storage.write(f"uploads/{eid}.pdf", pdf_bytes)

    initial_state = {
        "_pdf_path":          temp_pdf_path,
        "_rubric_raw":        rubric_raw,
        "exam_id":            eid,
        "course_id":          course_id,
        "students":           [],
        "current_review_idx": 0,
        "stats":              {},
        "error":              None,
        "rubric":             {},
    }

    # ── Register exam metadata ──────────────────────────────────────────────
    course_name = "Unknown Course"
    if course_id:
        db = get_db()
        course = await db.courses.find_one({"id": course_id})
        if course:
            course_name = course["code"]

    try:
        rubric_obj = json.loads(rubric_raw) if isinstance(rubric_raw, str) else rubric_raw
        rubric_name = rubric_obj.get("exam", "Unknown Rubric")
    except:
        rubric_name = "Invalid Rubric"

    await register_exam(ExamMetadata(
        id=eid,
        name=exam_name, # use user-provided name if possible
        course=course_name,
        courseId=course_id,
        rubric=rubric_name,
        uploaded=datetime.now().strftime("%b %d, %Y"),
        status="processing"
    ), current_user=current_user)

    # ── Run pipeline in thread pool (non-blocking) ────────────────────────────
    loop = asyncio.get_event_loop()
    loop.run_in_executor(_executor, _run_graph_sync, initial_state, eid)

    return {"exam_id": eid, "status": "processing"}


@router.get("/{exam_id}")
async def get_pipeline_state(exam_id: str, current_user: UserOut = Depends(get_current_user)):
    """
    Return the current pipeline state for an exam, pulling from MongoDB
    to ensure persistence across server restarts and after completion.
    """
    db = get_db()
    
    # 1. Check the primary 'exams' collection for status and metadata
    exam_meta = await db.exams.find_one({"id": exam_id})
    if not exam_meta:
        raise HTTPException(status_code=404, detail="Exam not found")
        
    course_id = exam_meta.get("courseId")
    if course_id:
        await verify_course_membership(course_id, current_user.id)
    
    current_status = exam_meta.get("status", "unknown")
    
    # 2. Get the active graph state (checkpointer should load this from MongoDB)
    snapshot = graph.get_state(_config(exam_id))
    next_review = None
    graph_students = []
    
    if snapshot and snapshot.values:
        graph_students = snapshot.values.get("students", [])
        if snapshot.tasks:
            for task in snapshot.tasks:
                if task.interrupts:
                    next_review = task.interrupts[0].value
                    # Sync status if it was just 'processing' but is now waiting
                    if current_status == "processing":
                        current_status = "awaiting_review"
                    break

    # 3. Fetch students and calculate progress
    students = []
    is_complete = False

    if current_status in ["graded", "complete"]:
        # Source of truth is the submissions collection
        cursor = db.submissions.find({"exam_id": exam_id}, {"_id": 0})
        students = await cursor.to_list(length=1000)
        is_complete = True
        # Double check if submissions exist; if not, maybe it's still finalizing?
        if not students and graph_students:
            students = graph_students
            is_complete = False # still in transition
    else:
        # Source of truth is the graph state
        if graph_students:
            students = graph_students
        else:
            # Fallback to submissions just in case
            cursor = db.submissions.find({"exam_id": exam_id}, {"_id": 0})
            students = await cursor.to_list(length=1000)
        
        # If graph is finished (no tasks) but status is still processing, it's complete
        if not next_review and snapshot and not snapshot.tasks:
            is_complete = True
            current_status = "graded"

    total_students = len(students)
    reviewed_count = 0
    
    for s in students:
        decision = s.get("ta_decision")
        # Handle both dict and string representations of TA decision
        if isinstance(decision, dict):
            if decision.get("action") and decision.get("action") not in ["pending", None]:
                reviewed_count += 1
        elif decision and decision not in ["pending", ""]:
            reviewed_count += 1
    
    # If the exam is marked graded in DB, ensure 100% progress
    if current_status in ["graded", "complete"]:
        reviewed_count = total_students

    return {
        "exam_id":     exam_id,
        "status":      current_status,
        "students":    students,
        "stats":       exam_meta.get("stats", {}),
        "error":       exam_meta.get("error"),
        "next_review": next_review,
        "is_complete": is_complete,
        "progress": {
            "total": total_students,
            "reviewed": reviewed_count
        }
    }


@router.get("/{exam_id}/export/csv")
async def export_gradebook_csv(exam_id: str, current_user: UserOut = Depends(get_current_user)):
    """
    Download the final gradebook for an exam as a CSV file.
    """
    db = get_db()
    exam_meta = await db.exams.find_one({"id": exam_id})
    if not exam_meta:
        raise HTTPException(status_code=404, detail="Exam not found")
    course_id = exam_meta.get("courseId")
    if course_id:
        await verify_course_membership(course_id, current_user.id)

    storage = get_storage()
    try:
        gradebook_data = storage.read(f"{exam_id}/gradebook.json")
    except Exception:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Gradebook for exam '{exam_id}' not found. "
                "Ensure all TA reviews are complete before exporting."
            ),
        )

    data = json.loads(gradebook_data)
    gradebook_entries = data.get("gradebook", [])
    stats = data.get("stats", {})
    rubric = data.get("rubric", {})
    total_marks = stats.get("total_marks", rubric.get("total_marks", 100))

    output = io.StringIO()
    writer = csv.writer(output)

    # Header row
    writer.writerow([
        "student_id",
        "final_score",
        "max_score",
        "ai_score",
        "percentage",
        "pass_fail",
        "ta_decision",
        "ta_comment",
        "ocr_confidence",
        "priority_review",
        "plagiarism_flag",
        "plagiarism_match",
    ])

    pass_threshold = total_marks * 0.5

    for entry in gradebook_entries:
        ai_grade = entry.get("ai_grade") or {}
        ta_decision = entry.get("ta_decision") or {}
        final_score = entry.get("final_score", 0.0)
        ai_score = ai_grade.get("total_score", 0.0) if ai_grade else 0.0
        pct = round((final_score / total_marks) * 100, 1) if total_marks else 0

        writer.writerow([
            entry.get("student_id", ""),
            final_score,
            total_marks,
            ai_score,
            f"{pct}%",
            "Pass" if final_score >= pass_threshold else "Fail",
            ta_decision.get("action", "approve"),
            ta_decision.get("comment", ""),
            round(entry.get("ocr_confidence", 1.0) * 100, 1),
            "Yes" if entry.get("needs_priority_review") else "No",
            "Yes" if entry.get("plagiarism_score") is not None else "No",
            entry.get("plagiarism_match", ""),
        ])

    csv_content = output.getvalue()
    filename = f"gradebook_{exam_id}.csv"

    return StreamingResponse(
        io.BytesIO(csv_content.encode("utf-8-sig")),  # utf-8-sig adds BOM for Excel
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{exam_id}/export/json")
async def export_gradebook_json(exam_id: str, current_user: UserOut = Depends(get_current_user)):
    """
    Download the raw gradebook JSON produced by the finalize agent.
    """
    db = get_db()
    exam_meta = await db.exams.find_one({"id": exam_id})
    if not exam_meta:
        raise HTTPException(status_code=404, detail="Exam not found")
    course_id = exam_meta.get("courseId")
    if course_id:
        await verify_course_membership(course_id, current_user.id)

    storage = get_storage()
    try:
        content = storage.read(f"{exam_id}/gradebook.json")
    except Exception:
        raise HTTPException(
            status_code=404,
            detail=f"Gradebook for exam '{exam_id}' not found.",
        )

    filename = f"gradebook_{exam_id}.json"

    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
