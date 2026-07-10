from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from .db import engine
from .services.analysis import InputCheckResult, check_input

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


@app.post("/api/input/check")
def input_check(req: InputCheckRequest) -> InputCheckResult:
    if len(req.text) > MAX_INPUT_CHARS:
        raise HTTPException(
            status_code=413,
            detail=f"Input too long ({len(req.text)} chars, max {MAX_INPUT_CHARS}).",
        )
    return check_input(req.text)
