"""Due sweep + demo reset tests (spec discussion 2026-07-18)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    GlobalDictionary,
    JobEventType,
    JobStatus,
    PendingQuiz,
    QuizGenerationJob,
    QuizStatus,
    User,
    UserMasteryMatrix,
)
from app.services.sweep import DEMO_SEED, reset_demo_accounts, sweep_due_items

NOW = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)


@pytest.fixture()
def factory():
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    make = sessionmaker(bind=engine, expire_on_commit=False)
    with make() as s:
        s.add(User(id=1, display_name="Owner"))
        s.add(User(id=2, display_name="Demo", is_demo=True))
        s.commit()
    return make


def _track(make, user_id: int, token: str, due: datetime) -> int:
    with make() as s:
        entity = GlobalDictionary(token=token, type="root_noun", language="fr")
        s.add(entity)
        s.flush()
        s.add(UserMasteryMatrix(
            user_id=user_id, entity_id=entity.id, next_review_date=due,
            interval_days=1, ease_factor=2.5, repetition=1,
        ))
        s.commit()
        return entity.id


def _jobs(make, user_id=None):
    with make() as s:
        q = select(QuizGenerationJob)
        if user_id is not None:
            q = q.where(QuizGenerationJob.user_id == user_id)
        return s.scalars(q).all()


def test_sweep_enqueues_one_capped_job_oldest_first(factory):
    ids = [
        _track(factory, 1, f"mot{i}", NOW - timedelta(days=i)) for i in range(12)
    ]
    _track(factory, 1, "pasdu", NOW + timedelta(days=3))  # not due: excluded

    enqueued = sweep_due_items(factory, now=NOW, max_items=10)
    jobs = _jobs(factory)
    assert len(jobs) == 1 and enqueued == {1: jobs[0].id}
    assert jobs[0].event_type == JobEventType.USER_ITEMS_DUE
    payload_ids = jobs[0].payload["entity_ids"]
    assert len(payload_ids) == 10
    assert payload_ids[0] == ids[11]  # most overdue first
    assert ids[0] not in payload_ids  # due "today" loses to older items at the cap


def test_sweep_is_idempotent_while_job_is_open(factory):
    _track(factory, 1, "mot", NOW - timedelta(days=1))
    sweep_due_items(factory, now=NOW)
    assert sweep_due_items(factory, now=NOW) == {}
    assert len(_jobs(factory)) == 1


def test_unanswered_quiz_blocks_resweep_answered_allows_it(factory):
    entity_id = _track(factory, 1, "mot", NOW - timedelta(days=1))
    sweep_due_items(factory, now=NOW)
    with factory() as s:
        job = s.scalars(select(QuizGenerationJob)).one()
        job.status = JobStatus.DONE
        s.add(PendingQuiz(user_id=1, quiz_data={"questions": []},
                          entity_ids=[entity_id], job_id=job.id))
        s.commit()
        quiz_id = s.scalars(select(PendingQuiz.id)).one()

    assert sweep_due_items(factory, now=NOW) == {}  # quiz still unanswered

    with factory() as s:
        s.get(PendingQuiz, quiz_id).status = QuizStatus.COMPLETED
        s.commit()
    # answered, item still due -> a fresh due-review job is allowed again
    assert 1 in sweep_due_items(factory, now=NOW)


def test_sweep_ignores_users_with_nothing_due(factory):
    _track(factory, 1, "mot", NOW + timedelta(days=5))
    assert sweep_due_items(factory, now=NOW) == {}
    assert _jobs(factory) == []


def test_demo_reset_restores_seed_and_leaves_owner_alone(factory):
    # messy demo state + owner state that must survive
    demo_entity = _track(factory, 2, "vieux", NOW - timedelta(days=9))
    owner_entity = _track(factory, 1, "mien", NOW - timedelta(days=1))
    with factory() as s:
        s.add(QuizGenerationJob(user_id=2, event_type=JobEventType.NEW_ITEM_ADDED,
                                payload={"entity_ids": [demo_entity]},
                                status=JobStatus.FAILED))
        s.add(PendingQuiz(user_id=2, quiz_data={"questions": []},
                          entity_ids=[demo_entity]))
        s.commit()

    assert reset_demo_accounts(factory) == [2]

    with factory() as s:
        demo_mastery = s.scalars(
            select(UserMasteryMatrix).where(UserMasteryMatrix.user_id == 2)
        ).all()
        assert len(demo_mastery) == len(DEMO_SEED)
        demo_quizzes = s.scalars(
            select(PendingQuiz).where(PendingQuiz.user_id == 2)
        ).all()
        assert demo_quizzes == []  # old quiz gone; new one comes via the job
        demo_jobs = _jobs(factory, user_id=2)
        assert len(demo_jobs) == 1  # re-seed enqueued exactly one fresh job
        assert demo_jobs[0].status == JobStatus.PENDING
        # owner untouched
        assert s.get(UserMasteryMatrix, (1, owner_entity)) is not None
        # shared dictionary rows are never deleted
        assert s.get(GlobalDictionary, demo_entity) is not None
        # seeded child got its parent link (storage path reused end to end)
        rows = {r.token: r for r in s.scalars(select(GlobalDictionary))}
        assert rows["mangé"].parent_id == rows["manger"].id


def test_demo_reset_twice_reuses_dictionary_rows(factory):
    reset_demo_accounts(factory)
    with factory() as s:
        count_after_first = len(s.scalars(select(GlobalDictionary)).all())
    reset_demo_accounts(factory)
    with factory() as s:
        assert len(s.scalars(select(GlobalDictionary)).all()) == count_after_first
