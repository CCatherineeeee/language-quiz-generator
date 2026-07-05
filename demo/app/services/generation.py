"""Question generation, grounded in the learner's profile and confirmed concepts.

Difficulty comes from the learner's current level; content is built around the
concepts they've confirmed they know, reinforcing ones due for review and adding
only a little new. This is what ties each exercise to the learner's real progress.
"""
import json
import random

from .. import db, prompts
from ..llm.client import parse_json
from ..store import make_client
from . import profile, review


def _focus_concepts(known, max_n=3):
    """Prefer concepts that are due for review, else a random sample of known ones."""
    if not known:
        return []
    due = {d["code"] for d in review.due_concepts(limit=20)}
    due_known = [c for c in known if c["code"] in due]
    pool = due_known or known
    return random.sample(pool, min(max_n, len(pool)))


def _persist(skill, content, focus_ids):
    q = db.execute(
        """INSERT INTO demo_questions (skill, level, content)
           VALUES (%s, %s, %s) RETURNING id""",
        (skill, content.get("_level", "A1"), json.dumps(content)),
    )
    qid = q["id"]
    for cid in focus_ids:
        db.execute(
            """INSERT INTO demo_question_concepts (question_id, concept_id)
               VALUES (%s, %s) ON CONFLICT DO NOTHING""",
            (qid, cid),
        )
    return qid


def generate(skill: str, topic: str = "") -> dict:
    level = profile.effective_level()
    known = profile.known_concepts()
    focus = _focus_concepts(known)

    grounding = prompts.GROUNDING.format(
        level=level,
        known=", ".join(c["name"] for c in known) or "(none yet — keep it very basic A1)",
        focus=", ".join(c["name"] for c in focus) or "(none — introduce a foundational point)",
    )

    template = {
        "reading": prompts.READING,
        "listening": prompts.LISTENING,
        "writing": prompts.WRITING,
        "speaking": prompts.SPEAKING,
    }[skill]

    client = make_client()
    messages = [
        {"role": "system", "content": prompts.SYSTEM.format(level=level)},
        {"role": "user", "content": template.format(
            level=level, grounding=grounding, topic=topic or "(your choice)")},
    ]
    json_mode = skill in ("reading", "listening")
    res = client.complete(messages, purpose="generation", json_mode=json_mode, temperature=0.8)
    content = parse_json(res["content"])
    content["_level"] = level

    qid = _persist(skill, content, [c["id"] for c in focus])

    public = {"question_id": qid, "skill": skill, "level": level,
              "provider": res["provider"],
              "focus": [c["name"] for c in focus],
              "personalized": bool(known)}

    if skill in ("reading", "listening"):
        public.update({"question": content.get("question"),
                       "options": content.get("options"),
                       "concept": content.get("concept")})
        public["passage" if skill == "reading" else "transcript"] = (
            content.get("passage") if skill == "reading" else content.get("transcript"))
    elif skill == "writing":
        public.update({k: content.get(k) for k in ("task", "word_count", "rubric", "concept")})
    elif skill == "speaking":
        public.update({k: content.get(k) for k in
                       ("task", "prep_time", "speak_time", "guidance", "concept")})
    return public
