"""Answer grading (features.md P0: SM-2 update needs a quality score).

Two grading paths:
- Multiple choice: deterministic, no LLM. Correct = quality 4 (recognition is
  easier than recall, so it never earns a 5); wrong = quality 1.
- Typed answers: LLM-graded via GRADING_SYSTEM_V1. The prompt's prime rule is
  avoiding false negatives (valid answer marked wrong).
"""

import json

from pydantic import BaseModel, Field

from app.llm.client import LLMClient
from app.prompts import GRADING_SYSTEM_V1

MCQ_CORRECT_QUALITY = 4
MCQ_WRONG_QUALITY = 1


class GradeResult(BaseModel):
    is_correct: bool
    quality: int = Field(ge=0, le=5, description="SM-2 recall score")
    feedback: str


def grade_mcq(chosen_index: int, correct_index: int, explanation: str) -> GradeResult:
    """No LLM. Correct -> just "Correct!"; wrong -> the explanation that was
    written at generation time (choice-specific analysis is P2)."""
    correct = chosen_index == correct_index
    return GradeResult(
        is_correct=correct,
        quality=MCQ_CORRECT_QUALITY if correct else MCQ_WRONG_QUALITY,
        feedback="Correct!" if correct else explanation,
    )


def grade_typed(
    question: str,
    expected: str,
    answer: str,
    language: str = "French",
    client: LLMClient | None = None,
) -> GradeResult:
    # Deterministic fast path: exact match after normalization needs no LLM.
    if answer.strip().lower().rstrip(".!?") == expected.strip().lower().rstrip(".!?"):
        return GradeResult(is_correct=True, quality=5, feedback="Perfect!")
    client = client or LLMClient()
    messages = [
        {"role": "system", "content": GRADING_SYSTEM_V1.format(language=language)},
        {
            "role": "user",
            "content": json.dumps(
                {"question": question, "expected_answer": expected, "learner_answer": answer},
                ensure_ascii=False,
            ),
        },
    ]
    return client.complete_structured(
        messages, GradeResult, purpose="grading", temperature=0.0
    )
