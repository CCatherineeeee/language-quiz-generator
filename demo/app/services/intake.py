"""Confirm-first intake: turn free-text 'what I know' into tracked concepts.

analyze() proposes concepts and asks clarifying questions but saves NOTHING.
confirm() takes the proposals the learner kept (plus any clarification answers),
finalizes them via one LLM pass, and only THEN writes them as status='known'
(TDD rule: nothing enters the active/known set without confirmation).
"""
import json

from .. import db, prompts
from ..llm.client import parse_json
from ..store import make_client
from . import profile


def analyze(text: str) -> dict:
    client = make_client()
    res = client.complete(
        [{"role": "system", "content": prompts.SYSTEM.format(level="A1")},
         {"role": "user", "content": prompts.INTAKE_ANALYZE.format(text=text)}],
        purpose="generation", json_mode=True, temperature=0.3,
    )
    out = parse_json(res["content"])
    out["provider"] = res["provider"]
    # Nothing is persisted here — these are proposals only.
    return out


def confirm(items: list[dict]) -> dict:
    """items: [{name, kind, level, answer?}] kept by the learner."""
    if not items:
        return {"saved": [], "level": profile.effective_level()}

    client = make_client()
    res = client.complete(
        [{"role": "system", "content": prompts.SYSTEM.format(level="A1")},
         {"role": "user", "content": prompts.INTAKE_CONFIRM.format(
             items=json.dumps(items, ensure_ascii=False))}],
        purpose="generation", json_mode=True, temperature=0.2,
    )
    final = parse_json(res["content"]).get("concepts", [])

    saved = []
    for c in final:
        code = c.get("code") or f"vocab:{c.get('name','')[:30].lower().replace(' ', '_')}"
        row = db.execute(
            """INSERT INTO demo_concepts (code, name, kind, level, description, status, meta)
               VALUES (%s, %s, %s, %s, %s, 'known', %s)
               ON CONFLICT (code) DO UPDATE
                 SET status='known', name=EXCLUDED.name, level=EXCLUDED.level,
                     description=EXCLUDED.description, meta=EXCLUDED.meta
               RETURNING id, code, name, level""",
            (code, c.get("name"), c.get("kind", "vocab"), c.get("level", "A1"),
             c.get("description"), json.dumps(c.get("meta")) if c.get("meta") else None),
        )
        db.execute("INSERT INTO demo_review_items (concept_id) VALUES (%s) "
                   "ON CONFLICT DO NOTHING", (row["id"],))
        saved.append(row)

    # Re-estimate level now that the known set changed.
    lvl = profile.suggest_level()
    return {"saved": saved, "level": lvl.get("level"), "rationale": lvl.get("rationale")}
