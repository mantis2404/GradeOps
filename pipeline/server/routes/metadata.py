"""
server/routes/metadata.py — Persistent storage for Courses, Rubrics, and Exams via MongoDB.
"""

from __future__ import annotations
import uuid
import asyncio
from datetime import datetime
from bson import ObjectId
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from pipeline.server.db import get_db
from pipeline.server.routes.auth import get_current_user, UserOut, check_role

router = APIRouter(prefix="/metadata", tags=["metadata"])

# ── Schemas ───────────────────────────────────────────────────────────────────

class CourseMember(BaseModel):
    user_id: str
    role: str # 'instructor' or 'ta'

class Course(BaseModel):
    id: str = Field(default_factory=lambda: f"course_{uuid.uuid4().hex[:8]}")
    name: str
    code: str
    members: list[CourseMember] = Field(default=[])

class AddMemberRequest(BaseModel):
    user_id: str
    role: str

class RubricMetadata(BaseModel):
    id: str = Field(default_factory=lambda: f"rubric_{uuid.uuid4().hex[:8]}")
    name: str
    questions: int = 0
    total_marks: float = 0
    created_at: str
    course_id: str | None = None

class ExamMetadata(BaseModel):
    id: str
    name: str
    course: str
    courseId: str | None = Field(default=None) # CamelCase to match frontend expectations
    rubric: str | None = None
    uploaded: str = Field(default_factory=lambda: datetime.now().strftime("%b %d, %Y"))
    status: str = "processing"
    students: int = 0
    reviewed: int = 0

class SaveRubricRequest(BaseModel):
    rubric_meta: RubricMetadata
    rubric_json: dict

# ── Helpers ───────────────────────────────────────────────────────────────────

async def verify_course_membership(course_id: str, user_id: str, required_role: str | None = None):
    db = get_db()
    
    # Check if user is global admin first
    db_user = await db.users.find_one({"_id": ObjectId(user_id)})
    if db_user and db_user.get("role") == "admin":
        course = await db.courses.find_one({"id": course_id})
        if not course:
            raise HTTPException(status_code=404, detail=f"Course {course_id} not found")
        return course

    course = await db.courses.find_one({"id": course_id})
    if not course:
        raise HTTPException(status_code=404, detail=f"Course {course_id} not found")
    
    members = course.get("members", [])
    if not members:
        # Legacy migration: if course has no members, and user is an instructor, migrate them
        if db_user and db_user.get("role") == "instructor":
            members = [{"user_id": user_id, "role": "instructor"}]
            await db.courses.update_one({"id": course_id}, {"$set": {"members": members}})
            course["members"] = members
            
    member = next((m for m in members if m["user_id"] == user_id), None)
    if not member:
        raise HTTPException(status_code=403, detail="Not a member of this course")
        
    if required_role:
        if required_role == "instructor" and member["role"] == "ta":
            raise HTTPException(status_code=403, detail="Instructor role required for this course")
            
    return course

# ── Routes: Courses ───────────────────────────────────────────────────────────

@router.get("/courses")
async def get_courses(current_user: UserOut = Depends(get_current_user)):
    db = get_db()
    if current_user.role == "admin":
        cursor = db.courses.find({}, {"_id": 0})
        return await cursor.to_list(length=100)

    # Return only courses where the user is a member
    cursor = db.courses.find({"members.user_id": current_user.id}, {"_id": 0})
    courses = await cursor.to_list(length=100)
    
    # Legacy migration during listing: if courses have no members at all, let global instructors see them
    # and auto-migrate them.
    if current_user.role == "instructor":
        legacy_cursor = db.courses.find({"members": {"$exists": False}}, {"_id": 0})
        legacy_courses = await legacy_cursor.to_list(length=100)
        for c in legacy_courses:
            members = [{"user_id": current_user.id, "role": "instructor"}]
            await db.courses.update_one({"id": c["id"]}, {"$set": {"members": members}})
            c["members"] = members
            courses.append(c)
            
    return courses

@router.post("/courses")
async def create_course(course: Course, current_user: UserOut = Depends(check_role("instructor"))):
    db = get_db()
    course_dict = course.model_dump()
    course_dict["members"] = [{
        "user_id": current_user.id,
        "role": "instructor"
    }]
    await db.courses.insert_one(course_dict)
    course.members = [CourseMember(user_id=current_user.id, role="instructor")]
    return course

@router.delete("/courses/id/{course_id}")
async def delete_course(course_id: str, current_user: UserOut = Depends(get_current_user)):
    await verify_course_membership(course_id, current_user.id, required_role="instructor")
    db = get_db()
    result = await db.courses.delete_one({"id": course_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Course not found")
    return {"status": "deleted"}

# ── Routes: Course Members ───────────────────────────────────────────────────

@router.get("/courses/id/{course_id}/members")
async def get_course_members(course_id: str, current_user: UserOut = Depends(get_current_user)):
    # Verify user has access to course
    course = await verify_course_membership(course_id, current_user.id)
    
    db = get_db()
    members = []
    for m in course.get("members", []):
        try:
            user_doc = await db.users.find_one({"_id": ObjectId(m["user_id"])})
            if user_doc:
                members.append({
                    "id": m["user_id"],
                    "name": user_doc.get("name", "Unknown"),
                    "email": user_doc.get("email", ""),
                    "role": m["role"]
                })
        except Exception:
            pass
    return members

@router.post("/courses/id/{course_id}/members")
async def add_course_member(course_id: str, req: AddMemberRequest, current_user: UserOut = Depends(get_current_user)):
    # Verify the current user is instructor of the course
    await verify_course_membership(course_id, current_user.id, required_role="instructor")
    
    db = get_db()
    # Check if target user exists
    target_user = await db.users.find_one({"_id": ObjectId(req.user_id)})
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
        
    # Check if already a member
    course = await db.courses.find_one({"id": course_id})
    if any(m.get("user_id") == req.user_id for m in course.get("members", [])):
        raise HTTPException(status_code=400, detail="User is already a member of this course")
        
    # Add member
    await db.courses.update_one(
        {"id": course_id},
        {"$push": {"members": {"user_id": req.user_id, "role": req.role}}}
    )
    return {"status": "success"}

@router.post("/courses/id/{course_id}/members/{user_id}/toggle-role")
async def toggle_course_member_role(course_id: str, user_id: str, current_user: UserOut = Depends(get_current_user)):
    # Verify the current user is instructor of the course
    await verify_course_membership(course_id, current_user.id, required_role="instructor")
    
    db = get_db()
    course = await db.courses.find_one({"id": course_id})
    members = course.get("members", [])
    
    member_idx = next((i for i, m in enumerate(members) if m.get("user_id") == user_id), None)
    if member_idx is None:
        raise HTTPException(status_code=404, detail="Member not found in course")
        
    new_role = "ta" if members[member_idx].get("role") == "instructor" else "instructor"
    
    await db.courses.update_one(
        {"id": course_id, "members.user_id": user_id},
        {"$set": {"members.$.role": new_role}}
    )
    return {"status": "success", "new_role": new_role}

@router.delete("/courses/id/{course_id}/members/{user_id}")
async def remove_course_member(course_id: str, user_id: str, current_user: UserOut = Depends(get_current_user)):
    # Verify the current user is instructor of the course
    await verify_course_membership(course_id, current_user.id, required_role="instructor")
    
    # Prevent removing yourself if you are the last instructor
    course = await db.courses.find_one({"id": course_id})
    members = course.get("members", [])
    if user_id == current_user.id:
        instructors = [m for m in members if m.get("role") == "instructor"]
        if len(instructors) <= 1:
            raise HTTPException(status_code=400, detail="Cannot remove yourself as you are the last instructor of this course")
            
    await db.courses.update_one(
        {"id": course_id},
        {"$pull": {"members": {"user_id": user_id}}}
    )
    return {"status": "deleted"}

# ── Routes: Rubrics ───────────────────────────────────────────────────────────

@router.get("/rubrics")
async def get_rubrics(current_user: UserOut = Depends(get_current_user)):
    db = get_db()
    if current_user.role == "admin":
        cursor = db.rubrics.find({}, {"_id": 0, "rubric_json": 0})
    else:
        # Fetch courses user belongs to
        user_courses = await db.courses.find({"members.user_id": current_user.id}).to_list(length=100)
        course_ids = [c["id"] for c in user_courses]
        cursor = db.rubrics.find({"course_id": {"$in": course_ids}}, {"_id": 0, "rubric_json": 0})
    
    return await cursor.to_list(length=100)

@router.post("/rubrics")
async def save_rubric(req: SaveRubricRequest, current_user: UserOut = Depends(get_current_user)):
    course_id = req.rubric_meta.course_id
    if not course_id:
        raise HTTPException(status_code=400, detail="course_id is required")
    await verify_course_membership(course_id, current_user.id, required_role="instructor")
    
    db = get_db()
    rubric_meta = req.rubric_meta.model_dump()
    rubric_json = req.rubric_json
    
    # Store both in the same document
    rubric_doc = {
        **rubric_meta,
        "rubric_json": rubric_json
    }
    
    # Update if exists, else insert
    await db.rubrics.update_one(
        {"id": rubric_meta["id"]},
        {"$set": rubric_doc},
        upsert=True
    )
    
    return req.rubric_meta

@router.get("/rubrics/{rubric_id}")
async def get_rubric(rubric_id: str, current_user: UserOut = Depends(get_current_user)):
    db = get_db()
    rubric = await db.rubrics.find_one({"id": rubric_id}, {"_id": 0})
    if not rubric:
        raise HTTPException(status_code=404, detail="Rubric not found")
    course_id = rubric.get("course_id")
    if course_id:
        await verify_course_membership(course_id, current_user.id)
    return rubric["rubric_json"]

@router.delete("/rubrics/{rubric_id}")
async def delete_rubric(rubric_id: str, current_user: UserOut = Depends(get_current_user)):
    db = get_db()
    rubric = await db.rubrics.find_one({"id": rubric_id})
    if not rubric:
        raise HTTPException(status_code=404, detail="Rubric not found")
    course_id = rubric.get("course_id")
    if course_id:
        await verify_course_membership(course_id, current_user.id, required_role="instructor")
    
    result = await db.rubrics.delete_one({"id": rubric_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Rubric not found")
    return {"status": "deleted"}

# ── Routes: Exams ─────────────────────────────────────────────────────────────

@router.get("/exams")
async def get_exams(current_user: UserOut = Depends(get_current_user)):
    db = get_db()
    if current_user.role == "admin":
        cursor = db.exams.find({}, {"_id": 0}).sort("uploaded", -1)
    else:
        # Fetch courses user belongs to
        user_courses = await db.courses.find({"members.user_id": current_user.id}).to_list(length=100)
        course_ids = [c["id"] for c in user_courses]
        cursor = db.exams.find({"courseId": {"$in": course_ids}}, {"_id": 0}).sort("uploaded", -1)
    
    exams = await cursor.to_list(length=100)
    
    from pipeline.graph import graph
    from pipeline.server.routes.pipeline import _config
    
    async def populate_exam(exam):
        eid = exam.get("id")
        status = exam.get("status")
        if not eid: return exam
        
        # 1. If graded, count from submissions collection
        if status in ["graded", "complete"]:
            total = await db.submissions.count_documents({"exam_id": eid})
            if total > 0:
                exam["students"] = total
                exam["reviewed"] = total
            elif "stats" in exam and exam["stats"].get("total_students"):
                exam["students"] = exam["stats"]["total_students"]
                exam["reviewed"] = exam["stats"]["total_students"]
        
        # 2. If processing, check active graph state for real-time progress
        elif status in ["processing", "awaiting_review"]:
            try:
                snapshot = graph.get_state(_config(eid))
                if snapshot and snapshot.values:
                    graph_students = snapshot.values.get("students", [])
                    exam["students"] = len(graph_students)
                    
                    reviewed_count = 0
                    for s in graph_students:
                        decision = s.get("ta_decision")
                        if isinstance(decision, dict):
                            if decision.get("action") and decision.get("action") not in ["pending", None]:
                                reviewed_count += 1
                        elif decision and decision not in ["pending", ""]:
                            reviewed_count += 1
                    exam["reviewed"] = reviewed_count
                    
                    has_interrupt = any(t.interrupts for t in snapshot.tasks)
                    if has_interrupt:
                        exam["status"] = "awaiting_review"
            except:
                pass
                
        return exam

    populated_exams = await asyncio.gather(*(populate_exam(e) for e in exams))
    return populated_exams

@router.post("/exams")
async def register_exam(exam: ExamMetadata, current_user: UserOut = Depends(get_current_user)):
    course_id = exam.courseId
    if not course_id:
        raise HTTPException(status_code=400, detail="courseId is required")
    await verify_course_membership(course_id, current_user.id, required_role="instructor")
    
    db = get_db()
    exam_dict = exam.model_dump()
    
    await db.exams.update_one(
        {"id": exam.id},
        {"$set": exam_dict},
        upsert=True
    )
    return exam

@router.delete("/exams/{exam_id}")
async def delete_exam(exam_id: str, current_user: UserOut = Depends(get_current_user)):
    db = get_db()
    exam = await db.exams.find_one({"id": exam_id})
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    course_id = exam.get("courseId")
    if course_id:
        await verify_course_membership(course_id, current_user.id, required_role="instructor")
        
    result = await db.exams.delete_one({"id": exam_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Exam not found")
    return {"status": "deleted"}
