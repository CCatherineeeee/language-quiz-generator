"""Grading. MCQ (reading/listening) is deterministic. Writing uses the LLM judge."""
import json

from .. import db, prompts
from ..llm.client import parse_json
from ..store import make_client
from . import profile, review


def _load_question(question_id: int) -> dict:
    row = db.query_one("SELECT skill, content FROM demo_questions WHERE id = %s",
                       (question_id,))
    if not row:
        raise ValueError(f"question {question_id} not found")
    content = row["content"]
    if isinstance(content, str):
        content = json.loads(content)
    return {"skill": row["skill"], "content": content}


def _record(question_id, answer, method, correct=None, scores=None, feedback=None):
    a = db.execute(
        "INSERT INTO demo_attempts (question_id, answer) VALUES (%s, %s) RETURNING id",
        (question_id, json.dumps(answer)),
    )
    db.execute(
        """INSERT INTO demo_gradings (attempt_id, method, correct, scores, feedback)
           VALUES (%s, %s, %s, %s, %s)""",
        (a["id"], method, correct,
         json.dumps(scores) if scores is not None else None, feedback),
    )
    # Update SM-2 scheduling for this question's concept.
    review.record_result(question_id, correct=correct, scores=scores)


def grade_mcq(question_id: int, choice: str) -> dict:
    q = _load_question(question_id)
    content = q["content"]
    correct_key = (content.get("correct") or "").strip().lower()
    chosen = (choice or "").strip().lower()
    is_correct = chosen == correct_key
    _record(question_id, {"choice": chosen}, "deterministic", correct=is_correct)
    out = {
        "correct": is_correct,
        "correct_option": correct_key,
        "explanation": content.get("explanation"),
    }
    if q["skill"] == "listening":
        out["transcript"] = content.get("transcript")  # reveal after answering
    return out


_BANDS = ["A1", "A2", "B1", "B2", "C1", "C2"]


def grade_writing(question_id: int, text: str) -> dict:
    q = _load_question(question_id)
    task = q["content"].get("task", "")
    level = q["content"].get("_level") or profile.effective_level()
    client = make_client()
    messages = [
        {"role": "system", "content": prompts.SYSTEM.format(level=level)},
        {"role": "user", "content": prompts.WRITING_JUDGE.format(
            level=level, task=task, answer=text)},
    ]
    res = client.complete(messages, purpose="grading", json_mode=True, temperature=0.2)
    judged = parse_json(res["content"])
    band = judged.get("overall_band")
    # "Passing" = meeting or exceeding the level the task was set at.
    try:
        passed = _BANDS.index(band) >= _BANDS.index(level)
    except ValueError:
        passed = band in ("B2", "C1", "C2")
    _record(question_id, {"text": text}, "llm_judge",
            correct=passed, scores=judged.get("scores"), feedback=judged.get("feedback"))
    judged["provider"] = res["provider"]
    return judged
