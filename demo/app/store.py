"""DB-backed helpers shared by services: LLM call logging, the client factory, and
posting system notices (e.g. provider switches) into the chat conversation."""
import json

from . import db
from .llm.client import LLMClient


def log_llm_call(provider, model, purpose, ok, error, latency_ms):
    db.execute(
        """INSERT INTO demo_llm_calls (provider, model, purpose, ok, error, latency_ms)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (provider, model, purpose, ok, error, latency_ms),
    )


def post_system_chat(kind, message):
    """Surface infra events (LLM provider switches, etc.) as a 'system' message in the
    chat log. Marked system so it's shown to the user but excluded from LLM context."""
    db.execute(
        "INSERT INTO demo_chat_messages (role, content, meta) VALUES ('system', %s, %s)",
        (message, json.dumps({"kind": kind, "system": True})),
    )


def make_client() -> LLMClient:
    return LLMClient(log_call=log_llm_call, notify=post_system_chat)
