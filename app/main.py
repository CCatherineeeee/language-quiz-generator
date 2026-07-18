from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from .db import SessionLocal, engine
from .services.analysis import (
    AmbiguityResult,
    InputCheckResult,
    check_ambiguity,
    check_input,
)
from .services.extraction import ExtractionResult, extract_knowledge
from .services.storage import (
    ConfirmedItem,
    DanglingParentError,
    StorageResult,
    store_confirmed_items,
)

app = FastAPI(title="Language Quiz Generator")

# Infra-level guardrail (features.md: never let the LLM see an oversized request).
MAX_INPUT_CHARS = 2000


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
