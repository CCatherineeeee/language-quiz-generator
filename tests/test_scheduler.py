"""SM-2 pure function + quiz submission flow (spec discussion 2026-07-18)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    GlobalDictionary,
    PendingQuiz,
    QuizStatus,
    User,
    UserMasteryMatrix,
)
from app.services.review import (
    AnswerMismatchError,
    QuizAlreadyCompletedError,
    SubmittedAnswer,
    submit_quiz,
)
from app.services.scheduler import MIN_EASE_FACTOR, sm2_next

NOW = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)


def test_canonical_success_sequence():
    """Published SM-2 behaviour: intervals go 1, 6, then interval * EF."""
    s = sm2_next(0, 2.5, 0, quality=5, now=NOW)
    assert (s.interval_days, s.repetition) == (1, 1)
    assert s.ease_factor == pytest.approx(2.6)

    s = sm2_next(s.interval_days, s.ease_factor, s.repetition, quality=5, now=NOW)
    assert (s.interval_days, s.repetition) == (6, 2)
    assert s.ease_factor == pytest.approx(2.7)

    s = sm2_next(s.interval_days, s.ease_factor, s.repetition, quality=4, now=NOW)
    assert (s.interval_days, s.repetition) == (16, 3)  # round(6 * 2.7)
    assert s.ease_factor == pytest.approx(2.7)  # quality 4 leaves EF unchanged
    assert s.next_review_date == NOW + timedelta(days=16)


def test_failure_resets_streak_and_drops_ease():
    s = sm2_next(16, 2.7, 3, quality=1, now=NOW)
    assert (s.interval_days, s.repetition) == (1, 0)  # relearn tomorrow
    assert s.ease_factor == pytest.approx(2.7 - 0.54)


def test_ease_factor_never_drops_below_floor():
    state = (1, MIN_EASE_FACTOR, 0)
    for _ in range(5):
        s = sm2_next(*state, quality=0, now=NOW)
        state = (s.interval_days, s.ease_factor, s.repetition)
    assert s.ease_factor == MIN_EASE_FACTOR


def test_quality_out_of_range_rejected():
    with pytest.raises(ValueError):
        sm2_next(0, 2.5, 0, quality=6)


# --- submission flow -------------------------------------------------------

MCQ_QUESTION = {
    "question_type": "mcq",
    "prompt_text": "Nous ___ au marché.",
    "choices": ["allons", "allez", "vont", "vais"],
    "correct_index": 0,
    "expected_answer": None,
    "explanation": "nous takes allons",
    "tested_point": "aller, present",
}
TRANSLATION_QUESTION = {
    "question_type": "translation",
    "prompt_text": "We are going to the market.",
    "choices": None,
    "correct_index": None,
    "expected_answer": "Nous allons au marché.",
    "explanation": "aller + à",
    "tested_point": "aller",
}


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


def _seed_quiz(make, question) -> tuple[int, int]:
    """One tracked entity + one single-question quiz; returns (quiz_id, entity_id)."""
    with make() as s:
        entity = GlobalDictionary(token="aller", type="root_verb", language="fr")
        s.add(entity)
        s.flush()
        s.add(UserMasteryMatrix(
            user_id=1, entity_id=entity.id, next_review_date=NOW,
            interval_days=0, ease_factor=2.5, repetition=0,
        ))
        quiz = PendingQuiz(
            user_id=1,
            quiz_data={"questions": [{"entity_id": entity.id, "question": question,
                                      "judge_overall": 5}]},
            entity_ids=[entity.id],
        )
        s.add(quiz)
        s.commit()
        return quiz.id, entity.id


def test_correct_mcq_advances_sm2_and_completes_quiz(factory):
    quiz_id, entity_id = _seed_quiz(factory, MCQ_QUESTION)
    with factory() as s:
        result = submit_quiz(
            s, quiz_id, [SubmittedAnswer(chosen_index=0)], now=NOW
        )
    out = result.outcomes[0]
    assert out.is_correct and out.quality == 4
    assert out.interval_days == 1 and out.next_review_date == NOW + timedelta(days=1)
    with factory() as s:
        row = s.get(UserMasteryMatrix, (1, entity_id))
        assert (row.repetition, row.interval_days) == (1, 1)
        assert s.get(PendingQuiz, quiz_id).status == QuizStatus.COMPLETED


def test_exact_translation_uses_fast_path_no_llm(factory):
    quiz_id, _ = _seed_quiz(factory, TRANSLATION_QUESTION)
    with factory() as s:
        # client=None: if the fast path missed, grade_typed would build a real
        # LLMClient and fail on network — passing here proves no LLM was used.
        result = submit_quiz(
            s, quiz_id,
            [SubmittedAnswer(typed_answer="nous allons au marché")], now=NOW,
        )
    assert result.outcomes[0].quality == 5


def test_double_submit_rejected_and_state_unchanged(factory):
    quiz_id, entity_id = _seed_quiz(factory, MCQ_QUESTION)
    with factory() as s:
        submit_quiz(s, quiz_id, [SubmittedAnswer(chosen_index=0)], now=NOW)
    with factory() as s, pytest.raises(QuizAlreadyCompletedError):
        submit_quiz(s, quiz_id, [SubmittedAnswer(chosen_index=1)], now=NOW)
    with factory() as s:
        row = s.get(UserMasteryMatrix, (1, entity_id))
        assert row.repetition == 1  # the wrong second answer changed nothing


def test_answer_count_mismatch_rejected(factory):
    quiz_id, _ = _seed_quiz(factory, MCQ_QUESTION)
    with factory() as s, pytest.raises(AnswerMismatchError):
        submit_quiz(
            s, quiz_id,
            [SubmittedAnswer(chosen_index=0), SubmittedAnswer(chosen_index=1)],
            now=NOW,
        )


def test_wrong_mcq_resets_to_relearn(factory):
    quiz_id, entity_id = _seed_quiz(factory, MCQ_QUESTION)
    with factory() as s:
        result = submit_quiz(s, quiz_id, [SubmittedAnswer(chosen_index=2)], now=NOW)
    out = result.outcomes[0]
    assert not out.is_correct and out.quality == 1
    assert out.feedback == MCQ_QUESTION["explanation"]
    with factory() as s:
        row = s.get(UserMasteryMatrix, (1, entity_id))
        assert (row.repetition, row.interval_days) == (0, 1)
