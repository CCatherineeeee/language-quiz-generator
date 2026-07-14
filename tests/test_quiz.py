import pytest
from pydantic import ValidationError

from app.services.generation import (
    JUDGE_RETRY_THRESHOLD,
    QuizPayload,
    QuizQuestion,
    generate_quiz_judged,
)
from app.services.grading import grade_mcq, grade_typed

PAYLOAD = QuizPayload(target_token="la soirée", type="gender_collocation")

MCQ = {
    "question_type": "mcq",
    "prompt_text": "J'ai passé une très bonne ___ avec mes amis.",
    "choices": ["soirée", "soir", "soirées", "soirs"],
    "correct_index": 0,
    "expected_answer": None,
    "explanation": "soirée is feminine and means an evening party.",
    "tested_point": "soirée is feminine",
}

GOOD_VERDICT = {
    "target_alignment": 5,
    "linguistic_authenticity": 5,
    "distractor_validity": 4,
    "overall": 4,
    "rationale": "none",
}


class SeqFakeLLM:
    """Returns queued payloads in order; records every call."""

    def __init__(self, payloads: list[dict]):
        self.payloads = list(payloads)
        self.calls = []

    def complete_structured(self, messages, schema, **kwargs):
        self.calls.append({"messages": messages, "schema": schema, **kwargs})
        return schema.model_validate(self.payloads.pop(0))


def test_mcq_requires_choices_and_index():
    with pytest.raises(ValidationError):
        QuizQuestion.model_validate({**MCQ, "choices": None})
    with pytest.raises(ValidationError):
        QuizQuestion.model_validate({**MCQ, "correct_index": None})


def test_translation_requires_expected_answer():
    with pytest.raises(ValidationError):
        QuizQuestion.model_validate(
            {**MCQ, "question_type": "translation", "expected_answer": None}
        )


def test_choices_must_be_distinct():
    with pytest.raises(ValidationError):
        QuizQuestion.model_validate({**MCQ, "choices": ["soirée", "Soirée ", "a", "b"]})


def test_judged_loop_no_retry_at_threshold():
    fake = SeqFakeLLM([MCQ, GOOD_VERDICT])
    quiz, verdict = generate_quiz_judged(PAYLOAD, client=fake)
    assert verdict.overall == JUDGE_RETRY_THRESHOLD
    assert len(fake.calls) == 2  # generate + judge, no retry


def test_judged_loop_retries_once_and_keeps_better():
    bad_verdict = {
        **GOOD_VERDICT,
        "distractor_validity": 1,
        "overall": 2,
        "rationale": "two defensible answers",
    }
    fake = SeqFakeLLM([MCQ, bad_verdict, MCQ, GOOD_VERDICT])
    quiz, verdict = generate_quiz_judged(PAYLOAD, client=fake)
    assert verdict.overall == 4
    assert len(fake.calls) == 4  # generate, judge, retry, judge
    # the retry request must carry the judge's rationale as a hint
    retry_user_msg = fake.calls[2]["messages"][-1]["content"]
    assert "two defensible answers" in retry_user_msg


def test_grade_mcq_correct_says_correct_only():
    r = grade_mcq(chosen_index=0, correct_index=0, explanation=MCQ["explanation"])
    assert r.is_correct and r.quality == 4 and r.feedback == "Correct!"


def test_grade_mcq_wrong_returns_stored_explanation():
    r = grade_mcq(chosen_index=2, correct_index=0, explanation=MCQ["explanation"])
    assert not r.is_correct and r.quality == 1
    assert r.feedback == MCQ["explanation"]


def test_grade_typed_fast_path_never_calls_llm():
    class Explodes:
        def complete_structured(self, *a, **k):
            raise AssertionError("fast path must not call the LLM")

    r = grade_typed(
        "Translate: hello",
        expected="Bonjour.",
        answer="  bonjour  ",
        client=Explodes(),
    )
    assert r.is_correct and r.quality == 5
