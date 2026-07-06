"""
agents/ocr.py — Agent 2: OCR / Vision transcription.

Sends each student's page images to Gemini Flash (a Vision Language Model)
and gets back a structured transcript with confidence score.

Rate-limit strategy (same as grading.py):
  - asyncio.Semaphore throttles concurrent Vision API calls to
    settings.llm_concurrency (default 2 — conservative for OCR free tier).
  - tenacity retries on 429 / 503 with exponential back-off, then pauses
    for exactly the retry-delay the API reports before giving up.
"""

from __future__ import annotations
import asyncio
import base64
import json
from pathlib import Path

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from pipeline.config import settings
from pipeline.schemas.outputs import OCROutput
from pipeline.state import ExamGradingState, StudentRecord




# ── Prompt ────────────────────────────────────────────────────────────────────

def _build_ocr_prompt() -> str:
    return (
        "You are transcribing a handwritten student exam answer. "
        "Return ONLY a JSON object with these exact keys:\n"
        "  - transcript (string): verbatim transcription of the handwritten text\n"
        "  - confidence (float 0-1): your confidence in the accuracy\n"
        "  - illegible_regions (list of strings): descriptions of any unreadable areas\n\n"
        "Do not add any commentary outside the JSON object."
    )


# ── Throttled OCR task ────────────────────────────────────────────────────────

async def _ocr_student_throttled(
    student: StudentRecord,
    model,
    semaphore: asyncio.Semaphore,
) -> OCROutput:
    """
    Run OCR for one student, respecting the concurrency semaphore.
    Retries on transient API errors with exponential back-off.
    """
    from langchain_core.messages import HumanMessage
    from langchain_google_genai.chat_models import ChatGoogleGenerativeAIError

    # Build message with all page images inline
    from pipeline.tools.storage import get_storage
    storage = get_storage()
    
    content: list[dict] = [{"type": "text", "text": _build_ocr_prompt()}]
    for page_path in student["page_paths"]:
        # Use storage.read(key) instead of Path(path).read_bytes()
        # The key is the path stored during ingestion
        try:
            img_bytes = storage.read(page_path)
            b64 = base64.b64encode(img_bytes).decode()
            content.append({
                "type":      "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}"},
            })
        except Exception as e:
            print(f"[ocr] Error reading image {page_path}: {e}")

    @retry(
        retry=retry_if_exception_type((ChatGoogleGenerativeAIError, Exception)),
        stop=stop_after_attempt(settings.llm_max_retries),
        wait=wait_exponential(multiplier=1, min=10, max=60),
        reraise=True,
    )
    async def _call() -> OCROutput:
        async with semaphore:
            response = await model.ainvoke([HumanMessage(content=content)])

        # Parse JSON — strip markdown fences if present
        raw = response.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()

        try:
            data = json.loads(raw)
            return OCROutput(**data)
        except (json.JSONDecodeError, TypeError) as exc:
            # If the LLM returned garbage, fall back gracefully
            return OCROutput(
                transcript=raw[:2000],  # keep whatever text was returned
                confidence=0.0,
                illegible_regions=[f"JSON parse error: {exc}"],
            )

    try:
        return await _call()
    except Exception as exc:
        return OCROutput(
            transcript=f"[API Error] Could not process image: {exc}",
            confidence=0.0,
            illegible_regions=["API Quota Exhausted"],
        )


async def _run_all_ocr(
    students: list[StudentRecord],
    model,
) -> list[OCROutput]:
    """Run OCR for all students concurrently, throttled by settings.llm_concurrency."""
    # Use a lower concurrency for OCR (vision calls are heavier than text calls)
    ocr_concurrency = max(1, settings.llm_concurrency // 2)
    semaphore = asyncio.Semaphore(ocr_concurrency)
    tasks = [_ocr_student_throttled(s, model, semaphore) for s in students]
    return await asyncio.gather(*tasks)


# ── Agent node ────────────────────────────────────────────────────────────────

def ocr_agent(state: ExamGradingState) -> dict:
    """
    LangGraph node function.
    Reads page_paths from each StudentRecord.
    Writes transcript and ocr_confidence back into each StudentRecord.
    """
    if state.get("error"):
        return {}

    students: list[StudentRecord] = list(state["students"])

    from langchain_google_genai import ChatGoogleGenerativeAI
    model = ChatGoogleGenerativeAI(
        model=settings.ocr_model,
        google_api_key=settings.google_api_key,
        temperature=0,
    )
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    results = loop.run_until_complete(_run_all_ocr(students, model))

    updated = []
    for student, ocr in zip(students, results):
        updated_student = dict(student)
        updated_student["transcript"]    = ocr.transcript
        updated_student["ocr_confidence"] = ocr.confidence
        updated_student["needs_priority_review"] = (
            ocr.confidence < settings.ocr_confidence_threshold
        )
        updated.append(updated_student)

    return {"students": updated}
