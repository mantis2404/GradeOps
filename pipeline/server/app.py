"""
server/app.py — FastAPI application factory.

Run with:
    uvicorn pipeline.server.app:app --reload --port 8000

Or from within the pipeline/ directory:
    uvicorn server.app:app --reload --port 8000

CORS is pre-configured to accept requests from the GradeOps frontend
(http://localhost:3000 by default — set CORS_ORIGINS in .env to change).
"""

from __future__ import annotations

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from pipeline.config import settings
from pipeline.server.routes.pipeline import router as pipeline_router
from pipeline.server.routes.review   import router as review_router
from pipeline.server.routes.metadata import router as metadata_router
from pipeline.server.routes.auth     import router as auth_router
from pipeline.server.routes.storage  import router as storage_router
from fastapi.staticfiles import StaticFiles
import os
from pipeline.server import ws as ws_manager
from pipeline.server.db import close_db_connection, create_indexes
from pipeline.server.routes.pipeline import resume_active_pipelines


def create_app() -> FastAPI:
    app = FastAPI(
        title="GradeOps Pipeline API",
        version="1.0.0",
        description=(
            "Multi-agent grading pipeline: ingestion → OCR → AI grading → "
            "HITL TA review → finalize. "
            "Connect the GradeOps frontend to this server to replace mock API calls."
        ),
    )

    @app.on_event("startup")
    async def startup_event():
        await create_indexes()
        await resume_active_pipelines()

    @app.on_event("shutdown")
    async def shutdown_event():
        await close_db_connection()

    # ── CORS ─────────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── REST routes ───────────────────────────────────────────────────────────
    app.include_router(pipeline_router)
    app.include_router(review_router)
    app.include_router(metadata_router)
    app.include_router(auth_router)
    app.include_router(storage_router)

    # ── WebSocket ─────────────────────────────────────────────────────────────
    @app.websocket("/ws/{exam_id}")
    async def websocket_endpoint(exam_id: str, websocket: WebSocket):
        """
        Connect to receive real-time stat updates for a specific exam.
        The finalize agent pushes data here after every student is reviewed.
        """
        await ws_manager.connect(exam_id, websocket)
        try:
            # Keep the connection alive — client sends pings if needed
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            ws_manager.disconnect(exam_id, websocket)

    # ── Health check ──────────────────────────────────────────────────────────
    @app.get("/health", tags=["meta"])
    async def health():
        return {
            "status": "ok",
            "grading_model": settings.grading_model,
            "ocr_model": settings.ocr_model,
        }

    # ── Static Files ──────────────────────────────────────────────────────────
    # Serve static files from the project root.
    # We mount this LAST so it doesn't shadow the API routes.
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    
    # Also mount the scratch directory specifically for images and uploads (LOCAL ONLY)
    if settings.storage_backend == "local":
        scratch_dir = os.path.abspath(settings.local_storage_path)
        if os.path.exists(scratch_dir):
            app.mount("/scratch", StaticFiles(directory=scratch_dir), name="scratch")
    
    app.mount("/", StaticFiles(directory=root_dir, html=True), name="static")

    return app


app = create_app()
