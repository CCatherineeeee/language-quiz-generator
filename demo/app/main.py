"""FastAPI app: serves the single-page UI and the practice API."""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db
from .config import SKILLS
from .llm.client import AllProvidersFailed
from .llm.providers import active_providers, PROVIDERS
from .services import chat, generation, grading, intake, profile, review

STATIC = Path(__file__).resolve().parents[1] / "static"

app = FastAPI(title="TCF B2 French Trainer (demo)")


@app.on_event("startup")
def _startup():
    db.init_db()


# ---------- request models ----------
class GenReq(BaseModel):
    skill: str
    topic: str = ""


class McqReq(BaseModel):
    question_id: int
    choice: str


class WritingReq(BaseModel):
    question_id: int
    text: str


class IntakeText(BaseModel):
    text: str


class IntakeConfirm(BaseModel):
    items: list[dict]


class LevelReq(BaseModel):
    level: str


class ChatReq(BaseModel):
    text: str


# ---------- API ----------
@app.get("/api/health")
def health():
    return {
        "ok": True,
        "providers": [
            {"name": p.name, "model": p.model, "active": p.active} for p in PROVIDERS
        ],
        "active_count": len(active_providers()),
    }


@app.post("/api/generate")
def api_generate(req: GenReq):
    if req.skill not in SKILLS:
        raise HTTPException(400, f"unknown skill: {req.skill}")
    try:
        return generation.generate(req.skill, req.topic)
    except AllProvidersFailed as e:
        raise HTTPException(503, f"All LLM providers failed: {e}")


@app.post("/api/grade/mcq")
def api_grade_mcq(req: McqReq):
    try:
        return grading.grade_mcq(req.question_id, req.choice)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.post("/api/grade/writing")
def api_grade_writing(req: WritingReq):
    if not req.text.strip():
        raise HTTPException(400, "empty submission")
    try:
        return grading.grade_writing(req.question_id, req.text)
    except AllProvidersFailed as e:
        raise HTTPException(503, f"All LLM providers failed: {e}")


# Provider-switch notices now post into the chat log (see store.post_system_chat),
# so the standalone notifications feed was removed.


@app.get("/api/review/due")
def api_review_due():
    return {"due": review.due_concepts()}


# ---------- profile + concepts ----------
@app.get("/api/profile")
def api_profile():
    return {"profile": profile.get_profile(), "known": profile.known_concepts()}


@app.post("/api/profile/level")
def api_set_level(req: LevelReq):
    return {"profile": profile.set_level(req.level, source="user")}


@app.post("/api/profile/suggest-level")
def api_suggest_level():
    try:
        return profile.suggest_level()
    except AllProvidersFailed as e:
        raise HTTPException(503, f"All LLM providers failed: {e}")


# ---------- chat tutor (multi-turn) ----------
@app.get("/api/chat")
def api_chat_history():
    return {"messages": chat.history()}


@app.post("/api/chat")
def api_chat_send(req: ChatReq):
    if not req.text.strip():
        raise HTTPException(400, "empty message")
    try:
        return chat.send(req.text)
    except AllProvidersFailed as e:
        raise HTTPException(503, f"All LLM providers failed: {e}")


@app.post("/api/chat/reset")
def api_chat_reset():
    chat.reset()
    return {"ok": True}


# ---------- intake (confirm-first) ----------
@app.post("/api/intake/analyze")
def api_intake_analyze(req: IntakeText):
    if not req.text.strip():
        raise HTTPException(400, "empty input")
    try:
        return intake.analyze(req.text)
    except AllProvidersFailed as e:
        raise HTTPException(503, f"All LLM providers failed: {e}")


@app.post("/api/intake/confirm")
def api_intake_confirm(req: IntakeConfirm):
    try:
        return intake.confirm(req.items)
    except AllProvidersFailed as e:
        raise HTTPException(503, f"All LLM providers failed: {e}")


# ---------- static UI ----------
@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
