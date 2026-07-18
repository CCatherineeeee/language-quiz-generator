"""Worker tests (spec in progress.md).

Most run on in-memory SQLite with a FakeLLM. The one thing SQLite cannot
test is FOR UPDATE SKIP LOCKED (it silently ignores the clause), so the
two-concurrent-claims test runs against the real Postgres and cleans up
after itself.
"""

import threading
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.db import SessionLocal as NeonSession
from app.models import (
    GlobalDictionary,
    JobEventType,
    JobStatus,
    PendingQuiz,
    QuizGenerationJob,
    User,
    UserMasteryMatrix,
)
from app.services.generation import JudgeVerdict, QuizQuestion
from app.worker import MAX_ATTEMPTS, _claim_next, tick

MCQ = {
    "question_type": "mcq",
    "prompt_text": "Nous ___ au marché.",
    "choices": ["allons", "allez", "vont", "vais"],
    "correct_index": 0,
    "expected_answer": None,
    "explanation": "nous takes allons",
    "tested_point": "aller, present tense",
}


class FakeLLM:
    """Returns a fixed quiz and a passing verdict; records every payload."""

    def __init__(self, fail_with: Exception | None = None):
        self.fail_with = fail_with
        self.calls = []

    def complete_structured(self, messages, schema, **kwargs):
        if self.fail_with is not None:
            raise self.fail_with
        self.calls.append(messages[-1]["content"])
        if schema is QuizQuestion:
            return QuizQuestion.model_validate(MCQ)
        return JudgeVerdict(
            target_alignment=5, linguistic_authenticity=5,
            distractor_validity=5, overall=5, rationale="solid",
        )


@pytest.fixture()
def factory():
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    make = sessionmaker(bind=engine, expire_on_commit=False)
    with make() as s:
        s.add(User(id=1, display_name="Test"))
        s.commit()
    return make


def _seed_job(make, *, repetition=0, attempts=0, status=JobStatus.PENDING,
              picked_up_at=None) -> int:
    """One tracked word + one job for it; returns the job id."""
    with make() as s:
        entity = GlobalDictionary(token="aller", type="root_verb", language="fr")
        s.add(entity)
        s.flush()
        s.add(UserMasteryMatrix(
            user_id=1, entity_id=entity.id, next_review_date=datetime.now(UTC),
            interval_days=0, ease_factor=2.5, repetition=repetition,
        ))
        job = QuizGenerationJob(
            user_id=1, event_type=JobEventType.NEW_ITEM_ADDED,
            payload={"entity_ids": [entity.id]}, status=status,
            attempts=attempts, picked_up_at=picked_up_at,
        )
        s.add(job)
        s.commit()
        return job.id


def _job(make, job_id):
    with make() as s:
        return s.get(QuizGenerationJob, job_id)


def _quizzes(make):
    with make() as s:
        return s.scalars(select(PendingQuiz)).all()


def test_happy_path_writes_quiz_and_marks_done(factory):
    job_id = _seed_job(factory)
    assert tick(factory, FakeLLM()) is True

    job = _job(factory, job_id)
    assert job.status == JobStatus.DONE
    quizzes = _quizzes(factory)
    assert len(quizzes) == 1
    assert quizzes[0].job_id == job_id
    assert quizzes[0].quiz_data["questions"][0]["question"]["question_type"] == "mcq"
    entity_id = quizzes[0].quiz_data["questions"][0]["entity_id"]
    assert quizzes[0].entity_ids == [entity_id]  # payload ids match the quiz


def test_practiced_item_gets_translation_question(factory):
    _seed_job(factory, repetition=2)
    fake = FakeLLM()
    tick(factory, fake)
    assert '"question_type": "translation"' in fake.calls[0]


def test_same_job_processed_twice_yields_one_quiz_row(factory):
    job_id = _seed_job(factory)
    tick(factory, FakeLLM())
    # simulate a reaped retry: the job goes back to PENDING after DONE work
    with factory() as s:
        s.get(QuizGenerationJob, job_id).status = JobStatus.PENDING
        s.commit()
    tick(factory, FakeLLM())
    assert len(_quizzes(factory)) == 1  # updated in place, not duplicated
    assert _job(factory, job_id).status == JobStatus.DONE


def test_reaper_recycles_stale_processing_job(factory):
    job_id = _seed_job(
        factory,
        status=JobStatus.PROCESSING,
        picked_up_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    tick(factory, FakeLLM())  # reaps it back to PENDING, then claims + finishes
    job = _job(factory, job_id)
    assert job.status == JobStatus.DONE
    assert job.attempts == 1  # the reap counted as a failed attempt


def test_attempts_cap_dead_letters_the_job(factory):
    job_id = _seed_job(factory, attempts=MAX_ATTEMPTS)
    assert tick(factory, FakeLLM()) is False  # buried, nothing left to claim
    assert _job(factory, job_id).status == JobStatus.FAILED
    assert _quizzes(factory) == []


def test_llm_failure_requeues_with_attempt_counted(factory):
    job_id = _seed_job(factory)
    tick(factory, FakeLLM(fail_with=RuntimeError("provider down")))
    job = _job(factory, job_id)
    assert job.status == JobStatus.PENDING
    assert job.attempts == 1
    assert _quizzes(factory) == []


def test_concurrent_claims_never_grab_the_same_job_live_postgres():
    """FOR UPDATE SKIP LOCKED semantics — needs real Postgres (Neon)."""
    with NeonSession() as s:
        jobs = [
            QuizGenerationJob(
                user_id=2, event_type=JobEventType.NEW_ITEM_ADDED,
                payload={"entity_ids": [], "probe": "skip-locked-test"},
            )
            for _ in range(2)
        ]
        s.add_all(jobs)
        s.commit()
        job_ids = {j.id for j in jobs}

    claimed, barrier = [], threading.Barrier(2)
    def claim():
        barrier.wait()
        got = _claim_next(NeonSession)
        if got is not None:
            claimed.append(got["job_id"])

    try:
        threads = [threading.Thread(target=claim) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(claimed) == len(set(claimed)), "two workers claimed the same job"
    finally:
        with NeonSession() as s, s.begin():
            for row in s.scalars(
                select(QuizGenerationJob).where(QuizGenerationJob.id.in_(job_ids))
            ):
                s.delete(row)
