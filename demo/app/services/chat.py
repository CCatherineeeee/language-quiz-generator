"""Conversational tutor. Multi-turn, persisted, and able to add/update/remove the
learner's known concepts mid-conversation via JSON `actions` (provider-agnostic, so
it works through the Groq->Gemini fallback)."""
import json
import re

from .. import db, prompts
from ..llm.client import parse_json
from ..store import make_client
from . import profile

HISTORY_LIMIT = 40


def _slug(name: str) -> str:
    s = re.sub(r"\(.*?\)", "", name or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s[:40] or "concept"


def history(limit: int = HISTORY_LIMIT):
    rows = db.query(
        """SELECT id, role, content, meta, created_at FROM demo_chat_messages
           ORDER BY id ASC LIMIT %s""",
        (limit,),
    )
    return rows


def reset():
    db.execute("DELETE FROM demo_chat_messages")


def _find_concept(action):
    code = action.get("code")
    if code:
        row = db.query_one("SELECT id, meta FROM demo_concepts WHERE code = %s", (code,))
        if row:
            return row
    name = action.get("name")
    if name:
        return db.query_one("SELECT id, meta FROM demo_concepts WHERE name = %s", (name,))
    return None


def _apply_actions(actions) -> list[dict]:
    applied = []
    for a in actions or []:
        op = (a.get("op") or "").lower()
        name = a.get("name", "")
        try:
            if op == "add":
                code = a.get("code") or f"{a.get('kind','vocab')}:{_slug(name)}"
                row = db.execute(
                    """INSERT INTO demo_concepts (code, name, kind, level, description, status, meta)
                       VALUES (%s, %s, %s, %s, %s, 'known', %s)
                       ON CONFLICT (code) DO UPDATE
                         SET status='known', name=EXCLUDED.name, level=EXCLUDED.level,
                             description=COALESCE(EXCLUDED.description, demo_concepts.description),
                             meta=COALESCE(EXCLUDED.meta, demo_concepts.meta)
                       RETURNING id""",
                    (code, name, a.get("kind", "vocab"), a.get("level", "A1"),
                     a.get("description"),
                     json.dumps(a.get("meta")) if a.get("meta") else None),
                )
                db.execute("INSERT INTO demo_review_items (concept_id) VALUES (%s) "
                           "ON CONFLICT DO NOTHING", (row["id"],))
                applied.append({"op": "added", "name": name or code})

            elif op == "update":
                row = _find_concept(a)
                if not row:
                    continue
                merged = dict(row.get("meta") or {})
                merged.update(a.get("meta") or {})
                db.execute(
                    """UPDATE demo_concepts
                       SET status='known',
                           level = COALESCE(%s, level),
                           description = COALESCE(%s, description),
                           meta = %s
                       WHERE id = %s""",
                    (a.get("level"), a.get("description"),
                     json.dumps(merged) if merged else None, row["id"]),
                )
                applied.append({"op": "updated", "name": a.get("name") or a.get("code")})

            elif op == "remove":
                row = _find_concept(a)
                if row:
                    db.execute("DELETE FROM demo_concepts WHERE id = %s", (row["id"],))
                    applied.append({"op": "removed", "name": a.get("name") or a.get("code")})
        except Exception as e:  # one bad action shouldn't kill the turn
            applied.append({"op": "error", "name": name, "error": str(e)[:120]})
    return applied


def send(text: str) -> dict:
    db.execute("INSERT INTO demo_chat_messages (role, content) VALUES ('user', %s)", (text,))

    known = profile.known_concepts()
    known_str = ", ".join(f"{c['name']} [{c['code']}]" for c in known) or "(none yet)"
    system = prompts.CHAT_SYSTEM.format(level=profile.effective_level(), known=known_str)

    convo = [{"role": "system", "content": system}]
    for m in history():
        # 'system' rows are infra notices (provider switches); show them in the UI but
        # keep them out of the model's conversation context.
        if m["role"] in ("user", "assistant"):
            convo.append({"role": m["role"], "content": m["content"]})

    client = make_client()
    res = client.complete(convo, purpose="generation", json_mode=True, temperature=0.5)
    data = parse_json(res["content"])
    reply = data.get("reply") or "…"
    actions = data.get("actions") or []
    applied = _apply_actions(actions)

    db.execute(
        "INSERT INTO demo_chat_messages (role, content, meta) VALUES ('assistant', %s, %s)",
        (reply, json.dumps({"applied": applied}) if applied else None),
    )
    return {"reply": reply, "applied": applied, "provider": res["provider"]}
