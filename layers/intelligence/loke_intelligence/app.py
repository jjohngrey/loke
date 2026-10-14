"""Composition root is the only intelligence file importing the memory implementation."""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from loke_contracts.models import (
    AnswerInput,
    ApiError,
    ClockAdvance,
    GoalInput,
    LearningInput,
    LearningView,
    ReminderSettings,
    TranscriptionResult,
)
from loke_memory.store import ConflictError, Store

from .audio import transcribe
from .coordinator import Coordinator
from .openrouter import OpenRouterError
from .scheduler import ReviewScheduler

ROOT = Path(__file__).resolve().parents[3]
load_dotenv(ROOT / ".env")


def create_app(database_url: str | None = None, learner_id: str | None = None):
    store = Store(database_url or os.getenv("DATABASE_URL", f"sqlite:///{ROOT / 'work/loke.db'}"))
    mode = os.getenv("MODEL_MODE", "demo")
    if mode not in {"demo", "live"}:
        raise ValueError("MODEL_MODE must be demo or live.")
    coordinator = Coordinator(store, mode)
    scheduler = ReviewScheduler(
        coordinator, store, float(os.getenv("SCHEDULER_INTERVAL_SECONDS", "30"))
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
        return coordinator.reminders(selected_learner, payload.enabled)

    @app.post("/api/demo/clock", dependencies=protected, response_model=LearningView)
    def clock(payload: ClockAdvance):
        return coordinator.advance_clock(selected_learner, payload.hours)

    @app.delete("/api/learner", dependencies=protected, response_model=LearningView)
    def delete_learner():
        store.delete_learner(selected_learner)
        return coordinator.view(selected_learner)

    @app.post("/api/audio/transcribe", dependencies=protected, response_model=TranscriptionResult)
    async def audio(file: UploadFile = File(...), audio_consent: str = Header(default="false")):
        if audio_consent != "true" or not coordinator.view(selected_learner).storage_consent:
            raise ValueError("Save a goal and consent to audio processing first.")
        data = await file.read(1_000_001)
        await file.close()
        text = await transcribe(data, file.filename or "recording.webm")
        return {"text": text, "provenance": "audio_transcription", "saved": False}

    return app


app = create_app()
