"""Composition root is the only intelligence file importing the memory implementation."""

import os
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, UploadFile
from loke_contracts.models import (
    AnswerInput,
    ApiError,
    AppCapabilities,
    ChatSettings,
    ClockAdvance,
    FolderInput,
    GoalInput,
    HistoryPage,
    LearningInput,
    LearningView,
    ReminderSettings,
    TranscriptionResult,
    UploadPreview,
    WorkspaceView,
)
from loke_memory.store import ConflictError, Store
from loke_memory.tiered import MemoryLimits

from .audio import transcribe
from .coordinator import Coordinator, fingerprint
from .openrouter import OpenRouterError
from .scheduler import ReviewScheduler
from .source_documents import MAX_BYTES, ingest_source

ROOT = Path(__file__).resolve().parents[3]
load_dotenv(ROOT / ".env")


def create_app(database_url: str | None = None, learner_id: str | None = None):
    store = Store(database_url or os.getenv("DATABASE_URL", "postgresql+psycopg://loke:loke@127.0.0.1:5432/loke"),
        MemoryLimits(summary_trigger=int(os.getenv("MEMORY_SUMMARY_TRIGGER_MESSAGES", "100")),
                     recent_messages=int(os.getenv("MEMORY_RECENT_MESSAGES", "40")),
                     leaf_records=int(os.getenv("MEMORY_LEAF_RECORD_LIMIT", "200")),
                     leaf_tokens=int(os.getenv("MEMORY_LEAF_TOKEN_LIMIT", "12000")),
                     context_tokens=int(os.getenv("MEMORY_CONTEXT_TOKEN_LIMIT", "3000"))))
    mode = os.getenv("MODEL_MODE", "demo")
    if mode not in {"demo", "live"}:
        raise ValueError("MODEL_MODE must be demo or live.")
    coordinator = Coordinator(store, mode)
    scheduler = ReviewScheduler(
        coordinator, store, float(os.getenv("SCHEDULER_INTERVAL_SECONDS", "30")),
        float(os.getenv("MEMORY_MAINTENANCE_INTERVAL_SECONDS", "900"))
    )
    selected_learner = learner_id or os.getenv("DEMO_LEARNER_ID", "demo-learner")
    token = os.getenv("SESSION_TOKEN", "local-demo-change-me")

    @asynccontextmanager
    async def lifespan(app):
        await scheduler.start()
        yield
        await scheduler.stop()
        store.engine.dispose()

    app = FastAPI(
        title="Loke intelligence layer",
        version="0.1.0",
        lifespan=lifespan,
        responses={code: {"model": ApiError} for code in (400, 403, 409, 502)},
    )
    app.state.store = store
    app.state.coordinator = coordinator

    def authorize(x_loke_session: str = Header(default="")):
        import secrets

        if not secrets.compare_digest(x_loke_session, token):
            raise HTTPException(status_code=403, detail="Local session token is required.")

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=409 if isinstance(exc, ConflictError) else 400, content={"detail": str(exc)}
        )

    @app.exception_handler(OpenRouterError)
    async def provider_error(request, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=502, content={"detail": str(exc)})

    @app.get("/healthz")
    def health():
        with store.engine.connect() as connection:
            from sqlalchemy import text

            connection.execute(text("SELECT 1"))
        return {"status": "ok", "mode": mode}

    protected = [Depends(authorize)]

    @app.get("/api/view", dependencies=protected, response_model=LearningView)
    def view():
        return coordinator.view(selected_learner)

    @app.post("/api/goal", dependencies=protected, response_model=LearningView)
    def goal(payload: GoalInput):
        return coordinator.goal(selected_learner, payload)

    @app.post("/api/input", dependencies=protected, response_model=LearningView)
    async def learning_input(payload: LearningInput):
        return await coordinator.input(selected_learner, payload)

    @app.post("/api/quiz/answer", dependencies=protected, response_model=LearningView)
    def answer(payload: AnswerInput):
        return coordinator.answer(selected_learner, payload)

    @app.post("/api/reminders", dependencies=protected, response_model=LearningView)
    def reminders(payload: ReminderSettings):
        return coordinator.reminders(selected_learner, payload.enabled, payload)

    @app.post("/api/demo/clock", dependencies=protected, response_model=LearningView)
    def clock(payload: ClockAdvance):
        return coordinator.advance_clock(selected_learner, payload.hours, payload)

    @app.delete("/api/learner", dependencies=protected, response_model=LearningView)
    def delete_learner(generation_id: str | None = None):
        store.delete_learner(selected_learner, generation_id)
        return coordinator.view(selected_learner)

    @app.get("/api/capabilities", dependencies=protected, response_model=AppCapabilities)
    def capabilities():
        return dict(audio_available=bool(os.getenv("OPENAI_API_KEY", "").strip() and shutil.which("ffprobe") and shutil.which("ffmpeg")), model_mode=mode)

    @app.get("/api/workspace", dependencies=protected, response_model=WorkspaceView)
    def workspace(offset: int = Query(default=0, ge=0)):
        return store.workspace(selected_learner, offset=offset)

    @app.get("/api/chats/history", dependencies=protected, response_model=HistoryPage)
    def history(chat_id: str = Query(min_length=1, max_length=100),
                generation_id: str = Query(min_length=1, max_length=100),
                before: int | None = Query(default=None, ge=1)):
        return store.chat_history(selected_learner, chat_id, generation_id, before)

    def update_workspace(payload, operation, transform):
        from loke_contracts.memory import CommitGuard
        if not payload.generation_id:
            raise ValueError("Reload the workspace before saving.")
        def apply(snapshot):
            if not snapshot["storage_consent"]:
                raise ValueError("Save a goal and consent before organizing your workspace.")
            transform(snapshot)
        store.mutate(selected_learner, payload.request_id, fingerprint(payload),
            payload.expected_state_revision, apply,
            guard=CommitGuard(generation_id=payload.generation_id), operation=operation)
        return store.workspace(selected_learner)

    @app.post("/api/workspace/folder", dependencies=protected, response_model=WorkspaceView)
    def folder(payload: FolderInput):
        def apply(snapshot):
            folders = snapshot.setdefault("workspace_folders", [])
            existing = next((f for f in folders if f["id"] == payload.id), None)
            if existing:
                existing["name"] = payload.name
            elif len(folders) < 200:
                folders.append(dict(id=payload.id, name=payload.name))
            else:
                raise ValueError("The workspace supports at most 200 folders.")
        return update_workspace(payload, "workspace_folder", apply)

    @app.post("/api/workspace/chat", dependencies=protected, response_model=WorkspaceView)
    def chat_settings(payload: ChatSettings):
        def apply(snapshot):
            if payload.folder_id and not any(f["id"] == payload.folder_id for f in snapshot.get("workspace_folders", [])):
                raise ValueError("Choose an existing folder.")
            chats = snapshot.setdefault("workspace_chats", {})
            if payload.id not in chats and len(chats) >= 1000:
                raise ValueError("The workspace supports settings for at most 1000 chats.")
            chats[payload.id] = dict(title=payload.title, folder_id=payload.folder_id)
        return update_workspace(payload, "workspace_chat", apply)

    @app.post("/api/attachments/preview", dependencies=protected, response_model=UploadPreview)
    async def attachment(file: UploadFile = File(...), generation_id: str | None = Header(default=None)):
        initial = coordinator.view(selected_learner)
        if not initial.storage_consent:
            raise ValueError("Save a goal and consent before processing attachments.")
        if generation_id is not None and generation_id != initial.generation_id:
            raise ConflictError("Learning history was reset. Reload before processing attachments.")
        try:
            data = await file.read(MAX_BYTES + 1)
            # PDF parsing is blocking; keep polling and other requests responsive.
            from starlette.concurrency import run_in_threadpool
            document = await run_in_threadpool(ingest_source, data, file.filename or "note.txt")
        finally:
            await file.close()
        text = "\n\n".join(page.text for page in document.pages).strip()
        if len(text) > 15000:
            raise ValueError("Use an excerpt with at most 15,000 extracted characters.")
        if coordinator.view(selected_learner).generation_id != initial.generation_id:
            raise ConflictError("Learning history was reset while processing the attachment.")
        return dict(text=text, filename=document.title, saved=False)

    @app.post("/api/audio/transcribe", dependencies=protected, response_model=TranscriptionResult)
    async def audio(file: UploadFile = File(...), audio_consent: str = Header(default="false"),
                    generation_id: str | None = Header(default=None)):
        initial = coordinator.view(selected_learner)
        if audio_consent != "true" or not initial.storage_consent:
            raise ValueError("Save a goal and consent to audio processing first.")
        try:
            data = await file.read(1_000_001)
        finally:
            await file.close()
        if generation_id is not None and generation_id != initial.generation_id:
            raise ConflictError("Learning history was reset. Reload before processing audio.")
        text = await transcribe(data, file.filename or "recording.webm")
        if coordinator.view(selected_learner).generation_id != initial.generation_id:
            raise ConflictError("Learning history was reset while transcribing audio.")
        return {"text": text, "provenance": "audio_transcription", "saved": False}

    return app


app = create_app()
