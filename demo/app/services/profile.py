"""Learner profile + LLM level suggestion."""
from .. import db, prompts
from ..llm.client import parse_json
from ..store import make_client


def get_profile() -> dict:
    row = db.query_one("SELECT * FROM demo_profile WHERE id = 1")
    if not row:
        db.execute("INSERT INTO demo_profile (id) VALUES (1) ON CONFLICT DO NOTHING")
        row = db.query_one("SELECT * FROM demo_profile WHERE id = 1")
    return row


def effective_level() -> str:
    p = get_profile()
    return p.get("current_level") or "A1"


def set_level(level: str, source: str = "user"):
    db.execute(
        """UPDATE demo_profile SET current_level = %s, level_source = %s,
           updated_at = now() WHERE id = 1""",
        (level, source),
    )
    return get_profile()


def known_concepts():
    return db.query(
        """SELECT id, code, name, kind, level, description, meta, created_at
           FROM demo_concepts
           WHERE status = 'known' ORDER BY kind, level, name"""
    )


def suggest_level() -> dict:
    concepts = known_concepts()
    if not concepts:
        set_level("A1", "suggested")
        return {"level": "A1", "rationale": "No concepts confirmed yet; starting at A1."}
    listing = "\n".join(f"- {c['name']} :: {c['level']}" for c in concepts)
    client = make_client()
    res = client.complete(
        [{"role": "system", "content": prompts.SYSTEM.format(level="A1")},
         {"role": "user", "content": prompts.LEVEL_SUGGEST.format(concepts=listing)}],
        purpose="grading", json_mode=True, temperature=0.1,
    )
    out = parse_json(res["content"])
    set_level(out.get("level", "A1"), "suggested")
    return out
