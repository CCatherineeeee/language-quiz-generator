"""SM-2-lite spaced repetition over concepts (TDD §4.4, hand-rolled & explainable).

A result is mapped to an SM-2 quality grade q (0..5); we update easiness, interval
and the next due date for every concept attached to the question.
"""
from datetime import datetime, timedelta, timezone

from .. import db


def _quality(correct, scores) -> int:
    # MCQ: correct -> 5, wrong -> 2.
    if scores is None:
        return 5 if correct else 2
    # Writing: scale by overall pass (B2+) -> 4, otherwise 2.
    return 4 if correct else 2


def _concept_ids(question_id: int):
    rows = db.query(
        "SELECT concept_id FROM demo_question_concepts WHERE question_id = %s",
        (question_id,),
    )
    return [r["concept_id"] for r in rows]


def record_result(question_id: int, correct, scores=None):
    q = _quality(correct, scores)
    now = datetime.now(timezone.utc)
    for cid in _concept_ids(question_id):
        row = db.query_one(
            "SELECT easiness, interval, reps FROM demo_review_items WHERE concept_id = %s",
            (cid,),
        )
        if row is None:
            db.execute("INSERT INTO demo_review_items (concept_id) VALUES (%s) "
                       "ON CONFLICT DO NOTHING", (cid,))
            ef, interval, reps = 2.5, 0, 0
        else:
            ef, interval, reps = row["easiness"], row["interval"], row["reps"]

        if q < 3:
            reps = 0
            interval = 1
        else:
            reps += 1
            if reps == 1:
                interval = 1
            elif reps == 2:
                interval = 6
            else:
                interval = round(interval * ef)
        ef = max(1.3, ef + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02)))
        due = now + timedelta(days=interval)
        db.execute(
            """UPDATE demo_review_items
               SET easiness=%s, interval=%s, reps=%s, due_at=%s
               WHERE concept_id=%s""",
            (ef, interval, reps, due, cid),
        )


def due_concepts(limit: int = 10):
    return db.query(
        """SELECT c.code, c.name, r.due_at, r.interval, r.reps
           FROM demo_review_items r JOIN demo_concepts c ON c.id = r.concept_id
           WHERE r.due_at <= now() AND c.status = 'known'
           ORDER BY r.due_at ASC LIMIT %s""",
        (limit,),
    )
