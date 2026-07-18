import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

import gradio as gr
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

from . import auth
from .db import SessionLocal, engine
from .services.analysis import (
    AmbiguityResult,
    InputCheckResult,
    check_ambiguity,
    check_input,
)
from .services.extraction import ExtractionResult, extract_knowledge
from .services.review import (
    AnswerMismatchError,
    QuizAlreadyCompletedError,
    SubmitResult,
    SubmittedAnswer,
    submit_quiz,
)
from .services.storage import (
    ConfirmedItem,
    DanglingParentError,
    StorageResult,
    store_confirmed_items,
)
from .ui import build_ui
from .worker import run_worker

# Without this the job-lifecycle logs (app/joblog.py) are silently dropped:
# Python's root logger defaults to WARNING and uvicorn only configures its own.
logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # One-service decision (2026-07-18): the quiz worker runs as a background
    # task inside this process. TestClient only triggers this when used as a
    # context manager, so unit tests never start the loop.
    worker_task = asyncio.create_task(run_worker())
    yield
    worker_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await worker_task


app = FastAPI(title="Language Quiz Generator", lifespan=lifespan)

# Infra-level guardrail (features.md: never let the LLM see an oversized request).
MAX_INPUT_CHARS = 2000


@app.get("/login")
def login(key: str):
    """Owner-only entrance: /login?key=<OWNER_SECRET> (see app/auth.py)."""
    if not auth.login_key_valid(key):
        raise HTTPException(status_code=403, detail="wrong key")
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(
        auth.COOKIE_NAME,
        auth.owner_cookie_value(),
        max_age=auth.COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return resp


@app.get("/logout")
def logout():
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie(auth.COOKIE_NAME)
    return resp


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/health/db")
def health_db():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok", "database": "reachable"}


class InputCheckRequest(BaseModel):
    text: str = Field(min_length=1)


def _guard_length(text: str) -> None:
    if len(text) > MAX_INPUT_CHARS:
        raise HTTPException(
            status_code=413,
            detail=f"Input too long ({len(text)} chars, max {MAX_INPUT_CHARS}).",
        )


@app.post("/api/input/check")
def input_check(req: InputCheckRequest) -> InputCheckResult:
    _guard_length(req.text)
    return check_input(req.text)


@app.post("/api/input/ambiguity")
def input_ambiguity(req: InputCheckRequest) -> AmbiguityResult:
    _guard_length(req.text)
    return check_ambiguity(req.text)


class ExtractionRequest(BaseModel):
    text: str = Field(min_length=1)
    resolved_meaning: str | None = None


@app.post("/api/input/extract")
def input_extract(req: ExtractionRequest) -> ExtractionResult:
    _guard_length(req.text)
    return extract_knowledge(req.text, resolved_meaning=req.resolved_meaning)


class StoreRequest(BaseModel):
    user_id: int
    items: list[ConfirmedItem] = Field(min_length=1)


@app.post("/api/knowledge/store")
def knowledge_store(req: StoreRequest) -> StorageResult:
    with SessionLocal() as session:
        try:
            return store_confirmed_items(session, req.user_id, req.items)
        except DanglingParentError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc


class SubmitRequest(BaseModel):
    answers: list[SubmittedAnswer] = Field(min_length=1)


@app.post("/api/quiz/{quiz_id}/submit")
def quiz_submit(quiz_id: int, req: SubmitRequest) -> SubmitResult:
    with SessionLocal() as session:
        try:
            return submit_quiz(session, quiz_id, req.answers)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except QuizAlreadyCompletedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except AnswerMismatchError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc


# Mounted last, at the root: the API routes above are matched first, and
# everything else (the recruiter-facing pages) goes to Gradio.
app = gr.mount_gradio_app(app, build_ui(), path="/")
