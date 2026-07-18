"""Async quiz worker (progress.md "Spec: async quiz worker").

Runs as a background asyncio task inside the FastAPI process (decision
2026-07-18: one service — Render's free tier has no free worker type, and at
this load the web app is never starved). Every ~3 seconds one `tick()` runs:

    1. reap   — a job stuck in PROCESSING for >2 min means a worker died
                mid-job; put it back in the queue (PENDING, attempts+1)
    2. bury   — a PENDING job that already failed 3 times is a poison job;
                mark it FAILED so it stops clogging the queue (dead-letter)
    3. claim  — take the oldest PENDING job with FOR UPDATE SKIP LOCKED so
                two workers can never grab the same one, mark it PROCESSING,
                and COMMIT — never hold a DB transaction across an LLM call
    4. generate — build one QuizPayload per entity and run the
                generate -> judge -> retry-once loop (services/generation.py)
    5. record — success: write pending_quizzes + job DONE in one transaction.
                The UNIQUE pending_quizzes.job_id makes retries idempotent:
                a re-run job overwrites its own quiz, never duplicates it.
                Failure: attempts+1, back to PENDING (or FAILED at the cap).

Every transition emits one JSON log line (app/joblog.py) with the job_id, so
a job's whole life is greppable in the deploy logs.
"""

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import sessionmaker

from app.db import SessionLocal
from app.joblog import log_event
from app.llm.client import LLMClient
from app.models import (
    GlobalDictionary,
    JobStatus,
    PendingQuiz,
    QuizGenerationJob,
    QuizStatus,
    UserMasteryMatrix,
)
from app.services.generation import QuizPayload, generate_quiz_judged
from app.services.sweep import reset_demo_accounts, sweep_due_items

logger = logging.getLogger(__name__)

TICK_SECONDS = 3
# The sweep is idempotent (open-work guard), so an hourly cadence is about
# freshness, not correctness — and it also runs right after every cold start.
SWEEP_INTERVAL_SECONDS = 3600
# ~4x the slowest observed LLM call: shorter risks double-generating a slow
# job, longer just delays recovery after a crash.
STALE_AFTER = timedelta(minutes=2)
MAX_ATTEMPTS = 3
# Worker rule (decision 2026-07-14): well-practiced items graduate from
# multiple-choice to harder free-form translation questions.
TRANSLATION_AT_REPETITION = 2


def _housekeep(session_factory: sessionmaker) -> None:
    """Steps 1+2: reap stale claims, bury poison jobs."""
    cutoff = datetime.now(UTC) - STALE_AFTER
    with session_factory() as session, session.begin():
        reaped = session.execute(
            update(QuizGenerationJob)
            .where(
                QuizGenerationJob.status == JobStatus.PROCESSING,
                QuizGenerationJob.picked_up_at < cutoff,
            )
            .values(status=JobStatus.PENDING, attempts=QuizGenerationJob.attempts + 1)
            .returning(QuizGenerationJob.id, QuizGenerationJob.user_id)
        ).all()
        buried = session.execute(
            update(QuizGenerationJob)
            .where(
                QuizGenerationJob.status == JobStatus.PENDING,
                QuizGenerationJob.attempts >= MAX_ATTEMPTS,
            )
            .values(status=JobStatus.FAILED)
            .returning(QuizGenerationJob.id, QuizGenerationJob.user_id)
        ).all()
    for job_id, user_id in reaped:
        log_event("JOB_REAPED", job_id=job_id, user_id=user_id)
    for job_id, user_id in buried:
        log_event("JOB_FAILED", job_id=job_id, user_id=user_id,
                  reason="attempts exhausted", dead_letter=True)


def _claim_next(session_factory: sessionmaker) -> dict | None:
    """Step 3: atomically claim the oldest PENDING job.

    Returns a plain dict (not the ORM object): the claim transaction is
    committed and closed before the slow LLM work starts.
    """
    with session_factory() as session, session.begin():
        job = session.scalars(
            select(QuizGenerationJob)
            .where(QuizGenerationJob.status == JobStatus.PENDING)
            .order_by(QuizGenerationJob.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        ).first()
        if job is None:
            return None
        job.status = JobStatus.PROCESSING
        job.picked_up_at = datetime.now(UTC)
        claimed = {
            "job_id": job.id,
            "user_id": job.user_id,
            "event_type": str(job.event_type),
            "payload": job.payload,
        }
    log_event("JOB_PICKED_UP", **claimed)
    return claimed


def _generate_quizzes(
    session_factory: sessionmaker, job: dict, client: LLMClient | None
) -> tuple[dict, list[int]]:
    """Step 4: the LLM work. No DB transaction is open while this runs."""
    entity_ids = list(job["payload"]["entity_ids"])
    with session_factory() as session:
        rows = session.execute(
            select(GlobalDictionary, UserMasteryMatrix)
            .join(UserMasteryMatrix, UserMasteryMatrix.entity_id == GlobalDictionary.id)
            .where(
                UserMasteryMatrix.user_id == job["user_id"],
                GlobalDictionary.id.in_(entity_ids),
            )
        ).all()
    if not rows:
        raise ValueError(f"job {job['job_id']}: no tracked entities for {entity_ids}")

    questions = []
    for entity, mastery in rows:
        payload = QuizPayload(
            target_token=entity.token,
            type=entity.type,
            question_type=(
                "translation"
                if mastery.repetition >= TRANSLATION_AT_REPETITION
                else "mcq"
            ),
            meaning_note=entity.meaning_note,
            linguistic_metadata=entity.linguistic_metadata,
            user_note=mastery.note,
        )
        quiz, verdict = generate_quiz_judged(payload, client=client)
        questions.append(
            {
                "entity_id": entity.id,
                "question": quiz.model_dump(),
                "judge_overall": verdict.overall,
            }
        )
    return {"questions": questions}, [entity.id for entity, _ in rows]


def _record_success(
    session_factory: sessionmaker,
    job: dict,
    quiz_data: dict,
    entity_ids: list[int],
    started: float,
) -> None:
    """Step 5, happy path: quiz row + job DONE in one transaction."""
    with session_factory() as session, session.begin():
        quiz = session.scalars(
            select(PendingQuiz).where(PendingQuiz.job_id == job["job_id"])
        ).first()
        if quiz is None:
            session.add(
                PendingQuiz(
                    user_id=job["user_id"],
                    quiz_data=quiz_data,
                    status=QuizStatus.PENDING,
                    entity_ids=entity_ids,
                    job_id=job["job_id"],
                )
            )
        else:  # a retry of a job whose first run died after writing the quiz
            quiz.quiz_data = quiz_data
            quiz.entity_ids = entity_ids
            quiz.status = QuizStatus.PENDING
        session.execute(
            update(QuizGenerationJob)
            .where(QuizGenerationJob.id == job["job_id"])
            .values(status=JobStatus.DONE)
        )
    log_event(
        "JOB_DONE",
        job_id=job["job_id"],
        user_id=job["user_id"],
        event_type=job["event_type"],
        latency_ms=int((time.monotonic() - started) * 1000),
    )


def _record_failure(session_factory: sessionmaker, job: dict, exc: Exception) -> None:
    """Step 5, failure path: back to PENDING, or FAILED at the attempts cap."""
    with session_factory() as session, session.begin():
        row = session.get(QuizGenerationJob, job["job_id"])
        row.attempts += 1
        row.status = (
            JobStatus.PENDING if row.attempts < MAX_ATTEMPTS else JobStatus.FAILED
        )
        attempts, dead = row.attempts, row.status == JobStatus.FAILED
    log_event(
        "JOB_FAILED",
        job_id=job["job_id"],
        user_id=job["user_id"],
        error=f"{type(exc).__name__}: {exc}",
        attempts=attempts,
        dead_letter=dead,
    )


def tick(
    session_factory: sessionmaker = SessionLocal, client: LLMClient | None = None
) -> bool:
    """One worker pass. Returns True if a job was claimed (tests use this)."""
    _housekeep(session_factory)
    job = _claim_next(session_factory)
    if job is None:
        return False
    started = time.monotonic()
    try:
        quiz_data, entity_ids = _generate_quizzes(session_factory, job, client)
    except Exception as exc:
        _record_failure(session_factory, job, exc)
        return True
    _record_success(session_factory, job, quiz_data, entity_ids, started)
    return True


async def run_worker() -> None:
    """The forever-loop FastAPI starts at boot (see lifespan in main.py).

    Three duties on one loop:
    - every tick (~3s): process one queued quiz job
    - hourly + at boot: sweep_due_items (enqueue due-review quizzes)
    - on UTC date change + at boot: reset_demo_accounts (recruiters always
      find a fresh demo; a cold start counts as "a new day" on purpose)

    All of it is sync (SQLAlchemy + LLM client), so each duty runs in a
    thread — the web app's event loop is never blocked. A crashing pass is
    logged and the loop keeps going; a job it was holding gets reaped two
    minutes later.
    """
    log_event("WORKER_STARTED", tick_seconds=TICK_SECONDS)
    last_sweep: float | None = None
    last_reset_date = None
    while True:
        try:
            today = datetime.now(UTC).date()
            if last_reset_date != today:
                await asyncio.to_thread(reset_demo_accounts)
                last_reset_date = today
            if last_sweep is None or time.monotonic() - last_sweep >= SWEEP_INTERVAL_SECONDS:
                await asyncio.to_thread(sweep_due_items)
                last_sweep = time.monotonic()
            await asyncio.to_thread(tick)
        except Exception:
            logger.exception("worker pass crashed")
        await asyncio.sleep(TICK_SECONDS)
