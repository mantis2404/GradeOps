"""
server/routes/review.py — TA decision endpoint.

POST /review/{exam_id}/decide

This is the endpoint the GradeOps frontend calls when a TA:
  - Approves an AI grade (key A)
  - Overrides a score (key O)
  - Escalates to instructor (key F / escalate)

It resumes the LangGraph graph by calling graph.invoke(Command(resume=...)).
Returns the same full state shape as GET /pipeline/{exam_id} so the
frontend does not need a separate re-poll after each decision — eliminating
the race condition that existed when the frontend had to call render() again.
"""

from __future__ import annotations
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Depends
from langgraph.types import Command
from pydantic import BaseModel, Field

from pipeline.graph import graph
from pipeline.server.db import get_db
from pipeline.server.routes.auth import get_current_user, UserOut
from pipeline.server.routes.metadata import verify_course_membership

router = APIRouter(prefix="/review", tags=["review"])


class ApproveDecision(BaseModel):
    action: Literal["approve"]


class OverrideDecision(BaseModel):
    action: Literal["override"]
    score:   float = Field(..., ge=0, description="New score to assign")
    comment: str   = Field(default="", description="TA's reason for the override")


class EscalateDecision(BaseModel):
    action: Literal["escalate"]


# Union type for the request body
class DecisionRequest(BaseModel):
    action: str
    score:  float | None = None
    comment: str = ""


def _config(exam_id: str) -> dict:
    return {"configurable": {"thread_id": exam_id}}


def _build_resume_value(req: DecisionRequest) -> Any:
    """
    Convert the HTTP request body to the value passed into Command(resume=...).
    This is exactly what the review_node receives as the return of interrupt().
    """
    if req.action == "approve":
        return "approve"
    elif req.action == "override":
        return {"action": "override", "score": req.score, "comment": req.comment}
    elif req.action == "escalate":
        return "escalate"
    else:
        raise ValueError(f"Unknown action: {req.action!r}")


@router.post("/{exam_id}/decide")
async def submit_decision(exam_id: str, body: DecisionRequest, current_user: UserOut = Depends(get_current_user)):
    """
    Submit a TA decision for the currently pending review in an exam.
    """
    db = get_db()
    exam_meta = await db.exams.find_one({"id": exam_id})
    if exam_meta:
        course_id = exam_meta.get("courseId")
        if course_id:
            await verify_course_membership(course_id, current_user.id, required_role="ta")

    # Check that the exam exists and has a pending interrupt
    snapshot = graph.get_state(_config(exam_id))
    if not snapshot:
        raise HTTPException(status_code=404, detail=f"Exam {exam_id!r} not found")

    has_interrupt = any(task.interrupts for task in snapshot.tasks)
    if not has_interrupt:
        raise HTTPException(
            status_code=409,
            detail="No pending review for this exam. It may already be finalized.",
        )

    try:
        resume_value = _build_resume_value(body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # ── Run pipeline resume in thread pool, then await completion ─────────────
    import asyncio
    from pipeline.server.routes.pipeline import _executor, _resume_graph_sync, get_pipeline_state

    cmd = Command(resume=resume_value)
    loop = asyncio.get_event_loop()

    # await so we read state only after graph settles at next interrupt or END
    await loop.run_in_executor(_executor, _resume_graph_sync, cmd, exam_id)

    # ── Return the unified state shape ────────────────────────────────────────
    return await get_pipeline_state(exam_id, current_user=current_user)
