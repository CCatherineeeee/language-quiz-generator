"""Daily due sweep + demo-account reset (features.md P0).

sweep_due_items() is the USER_ITEMS_DUE producer: for every user with
mastery rows past their next_review_date, enqueue ONE quiz job carrying the
longest-overdue items (capped). The guard makes it idempotent: a user with
anything already in flight (an open job or an unanswered quiz) is skipped,
so running the sweep hourly, or repeatedly after cold starts, can never
pile up duplicate quizzes.

reset_demo_accounts() restores every is_demo user to a fixed starter state,
so each recruiter demo starts identical. It only ever touches rows owned by
is_demo users, and only their per-user rows (mastery, quizzes, jobs) —
global_dictionary rows are shared with real users and are never deleted.

Both are called by the worker loop (worker.py): sweep hourly, reset when
the UTC date changes and once at every boot.
"""

from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import sessionmaker

from app.db import SessionLocal
from app.joblog import log_event
from app.models import (
    JobEventType,
    JobStatus,
    PendingQuiz,
    QuizGenerationJob,
    QuizStatus,
    User,
    UserMasteryMatrix,
)
from app.services.storage import ConfirmedItem, store_confirmed_items

MAX_ITEMS_PER_SWEEP = 10

# What a fresh demo account knows. Seeding goes through the normal storage
# transaction, so it also enqueues the job that generates the demo's first quiz.
DEMO_SEED = [
    ConfirmedItem(token="bonjour", type="phrase", meaning_note="hello",
                  linguistic_metadata={"register": "neutral"}),
    ConfirmedItem(token="manger", type="root_verb", meaning_note="to eat",
                  linguistic_metadata={"group": "first", "aux": "avoir"}),
    ConfirmedItem(token="mangé", type="conjugation",
                  linguistic_metadata={"form": "past participle"},
                  parent_token="manger"),
    ConfirmedItem(token="soirée", type="root_noun", meaning_note="evening party",
                  linguistic_metadata={"gender": "feminine"}),
]


def _user_has_open_work(session, user_id: int) -> bool:
    """Anything in flight — open job (either type) or unanswered quiz —
    means the sweep must not add more work for this user yet."""
    open_job = session.scalars(
        select(QuizGenerationJob.id)
        .where(
            QuizGenerationJob.user_id == user_id,
            QuizGenerationJob.status.in_([JobStatus.PENDING, JobStatus.PROCESSING]),
        )
        .limit(1)
    ).first()
    if open_job is not None:
        return True
    open_quiz = session.scalars(
        select(PendingQuiz.id)
        .where(
            PendingQuiz.user_id == user_id,
            PendingQuiz.status == QuizStatus.PENDING,
        )
        .limit(1)
    ).first()
    return open_quiz is not None


def sweep_due_items(
    session_factory: sessionmaker = SessionLocal,
    now: datetime | None = None,
    max_items: int = MAX_ITEMS_PER_SWEEP,
) -> dict[int, int]:
    """Returns {user_id: enqueued job_id} for users that got a due-review job."""
    now = now or datetime.now(UTC)
    enqueued: dict[int, int] = {}
    with session_factory() as session, session.begin():
        due_user_ids = session.scalars(
            select(UserMasteryMatrix.user_id)
            .where(UserMasteryMatrix.next_review_date <= now)
            .distinct()
        ).all()
        for user_id in due_user_ids:
            if _user_has_open_work(session, user_id):
                continue
            due_ids = session.scalars(
                select(UserMasteryMatrix.entity_id)
                .where(
                    UserMasteryMatrix.user_id == user_id,
                    UserMasteryMatrix.next_review_date <= now,
                )
                .order_by(UserMasteryMatrix.next_review_date)  # longest-overdue first
                .limit(max_items)
            ).all()
            job = QuizGenerationJob(
                user_id=user_id,
                event_type=JobEventType.USER_ITEMS_DUE,
                payload={"entity_ids": list(due_ids)},
                status=JobStatus.PENDING,
            )
            session.add(job)
            session.flush()
            enqueued[user_id] = job.id
    for user_id, job_id in enqueued.items():
        log_event("JOB_ENQUEUED", job_id=job_id, user_id=user_id,
                  event_type=str(JobEventType.USER_ITEMS_DUE))
    return enqueued


def reset_demo_accounts(session_factory: sessionmaker = SessionLocal) -> list[int]:
    """Wipe and re-seed every is_demo user. Never touches anyone else."""
    with session_factory() as session:
        demo_ids = session.scalars(select(User.id).where(User.is_demo)).all()

    reset_ids: list[int] = []
    for user_id in demo_ids:
        with session_factory() as session, session.begin():
            user = session.get(User, user_id)
            if user is None or not user.is_demo:  # re-verify inside the transaction
                continue
            # quizzes first: their job_id FK points at the jobs deleted next
            session.execute(delete(PendingQuiz).where(PendingQuiz.user_id == user_id))
            session.execute(
                delete(QuizGenerationJob).where(QuizGenerationJob.user_id == user_id)
            )
            session.execute(
                delete(UserMasteryMatrix).where(UserMasteryMatrix.user_id == user_id)
            )
        # Fresh session: store_confirmed_items opens its own transaction.
        with session_factory() as session:
            store_confirmed_items(session, user_id, DEMO_SEED)
        reset_ids.append(user_id)
        log_event("DEMO_RESET", user_id=user_id)
    return reset_ids
