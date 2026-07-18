"""SM-2 spaced-repetition scheduler (features.md P0).

sm2_next() is the published SuperMemo-2 algorithm, unmodified, as a pure
function: same inputs always give the same output, no database, no clock of
its own (the caller passes `now`). That makes it trivially unit-testable and
swappable — a better scheduler (e.g. FSRS) would replace this one function.

apply_review() is the thin bridge to the database: it runs sm2_next on a
user_mastery_matrix row and writes the new state back. It joins the caller's
transaction so a quiz's items all update atomically (see services/review.py).
"""

from datetime import UTC, datetime, timedelta

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.models import UserMasteryMatrix

MIN_EASE_FACTOR = 1.3


class Sm2State(BaseModel):
    interval_days: int
    ease_factor: float
    repetition: int
    next_review_date: datetime


def sm2_next(
    interval_days: int,
    ease_factor: float,
    repetition: int,
    quality: int,
    now: datetime | None = None,
) -> Sm2State:
    if not 0 <= quality <= 5:
        raise ValueError(f"quality must be 0-5, got {quality}")
    now = now or datetime.now(UTC)

    if quality >= 3:  # successful recall
        repetition += 1
        if repetition == 1:
            interval_days = 1  # first success: see it again tomorrow
        elif repetition == 2:
            interval_days = 6  # second: in about a week
        else:
            interval_days = round(interval_days * ease_factor)  # then exponential
    else:  # failed recall: streak broken, relearn tomorrow
        repetition = 0
        interval_days = 1

    # Every answer nudges the ease factor: q=5 raises it, q=4 keeps it,
    # anything lower drops it — but never below the SM-2 floor of 1.3.
    ease_factor += 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)
    ease_factor = max(MIN_EASE_FACTOR, ease_factor)

    return Sm2State(
        interval_days=interval_days,
        ease_factor=ease_factor,
        repetition=repetition,
        next_review_date=now + timedelta(days=interval_days),
    )


def apply_review(
    session: Session,
    user_id: int,
    entity_id: int,
    quality: int,
    now: datetime | None = None,
) -> Sm2State:
    """Advance one mastery row. Joins the caller's open transaction."""
    row = session.get(UserMasteryMatrix, (user_id, entity_id))
    if row is None:
        raise LookupError(f"user {user_id} does not track entity {entity_id}")
    state = sm2_next(row.interval_days, row.ease_factor, row.repetition, quality, now)
    row.interval_days = state.interval_days
    row.ease_factor = state.ease_factor
    row.repetition = state.repetition
    row.next_review_date = state.next_review_date
    return state
