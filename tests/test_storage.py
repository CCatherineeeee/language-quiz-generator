"""Storage transaction tests (spec in progress.md).

SQLite in-memory stands in for Postgres: transaction begin/flush/rollback
semantics are the same at this level, and tests need no network.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.main
from app.db import Base
from app.models import GlobalDictionary, QuizGenerationJob, User, UserMasteryMatrix
from app.services import storage
from app.services.storage import (
    ConfirmedItem,
    DanglingParentError,
    store_confirmed_items,
)


def _engine():
    # StaticPool: one shared connection, so every session (and the TestClient
    # threadpool) sees the same in-memory database.
    return create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )


@pytest.fixture()
def session():
    engine = _engine()
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(User(id=1, display_name="Test"))
        s.commit()
        yield s


def _rows(session, model):
    return session.scalars(select(model)).all()


def test_both_meanings_create_two_rows_and_one_job(session):
    items = [
        ConfirmedItem(token="soirée", type="root_noun", meaning_note="evening"),
        ConfirmedItem(token="soirée", type="root_noun", meaning_note="party"),
    ]
    result = store_confirmed_items(session, 1, items)

    dict_rows = _rows(session, GlobalDictionary)
    mastery_rows = _rows(session, UserMasteryMatrix)
    jobs = _rows(session, QuizGenerationJob)
    assert len(dict_rows) == 2
    assert len(mastery_rows) == 2
    assert len(jobs) == 1
    assert sorted(jobs[0].payload["entity_ids"]) == sorted(r.id for r in dict_rows)
    assert result.job_id == jobs[0].id
    assert len(result.stored) == 2 and result.already_tracked == []


def test_new_mastery_row_starts_with_fresh_sm2_state(session):
    store_confirmed_items(session, 1, [ConfirmedItem(token="manger", type="root_verb")])
    row = _rows(session, UserMasteryMatrix)[0]
    assert (row.interval_days, row.ease_factor, row.repetition) == (0, 2.5, 0)


def test_readding_known_word_adds_nothing_and_reports_it(session):
    items = [ConfirmedItem(token="manger", type="root_verb")]
    store_confirmed_items(session, 1, items)
    result = store_confirmed_items(session, 1, items)

    assert result.stored == []
    assert result.already_tracked == ["manger"]
    assert result.job_id is None
    assert len(_rows(session, GlobalDictionary)) == 1
    assert len(_rows(session, UserMasteryMatrix)) == 1
    assert len(_rows(session, QuizGenerationJob)) == 1  # only the first call's job


def test_child_links_to_parent_created_in_same_batch(session):
    # Child listed first on purpose: the parents-first sort must fix the order.
    items = [
        ConfirmedItem(token="mangé", type="conjugation", parent_token="manger"),
        ConfirmedItem(token="manger", type="root_verb"),
    ]
    store_confirmed_items(session, 1, items)
    rows = {r.token: r for r in _rows(session, GlobalDictionary)}
    assert rows["mangé"].parent_id == rows["manger"].id


def test_child_links_to_parent_already_in_dictionary(session):
    store_confirmed_items(session, 1, [ConfirmedItem(token="manger", type="root_verb")])
    store_confirmed_items(
        session,
        1,
        [ConfirmedItem(token="mangé", type="conjugation", parent_token="manger")],
    )
    rows = {r.token: r for r in _rows(session, GlobalDictionary)}
    assert rows["mangé"].parent_id == rows["manger"].id


def test_dangling_parent_rolls_back_the_whole_batch(session):
    items = [
        ConfirmedItem(token="manger", type="root_verb"),
        ConfirmedItem(token="mangé", type="conjugation", parent_token="mangre"),
    ]
    with pytest.raises(DanglingParentError):
        store_confirmed_items(session, 1, items)
    assert _rows(session, GlobalDictionary) == []
    assert _rows(session, UserMasteryMatrix) == []
    assert _rows(session, QuizGenerationJob) == []


def test_failure_at_enqueue_rolls_back_dictionary_and_mastery_writes(
    session, monkeypatch
):
    def boom(**kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(storage, "QuizGenerationJob", boom)
    with pytest.raises(RuntimeError):
        store_confirmed_items(
            session, 1, [ConfirmedItem(token="soirée", type="root_noun")]
        )
    assert _rows(session, GlobalDictionary) == []
    assert _rows(session, UserMasteryMatrix) == []


def test_store_endpoint_happy_path_and_dangling_parent_422(monkeypatch):
    engine = _engine()
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as s:
        s.add(User(id=1, display_name="Test"))
        s.commit()
    monkeypatch.setattr(app.main, "SessionLocal", factory)
    client = TestClient(app.main.app)

    ok = client.post(
        "/api/knowledge/store",
        json={"user_id": 1, "items": [{"token": "soirée", "type": "root_noun"}]},
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["stored"][0]["token"] == "soirée"
    assert body["job_id"] is not None

    bad = client.post(
        "/api/knowledge/store",
        json={
            "user_id": 1,
            "items": [
                {"token": "mangé", "type": "conjugation", "parent_token": "mangre"}
            ],
        },
    )
    assert bad.status_code == 422
