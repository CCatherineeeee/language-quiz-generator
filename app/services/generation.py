"""Quiz generation (features.md P0: Quiz generator).

The worker calls generate_quiz_judged() per due/new item: generate -> judge ->
regenerate once with the judge's rationale if overall < 4 -> keep the better
version. Sub-threshold quizzes are logged for threshold tuning (agreed 2026-07:
start at 4, revisit with data).
"""

import json
import logging
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.llm.client import LLMClient
from app.prompts import JUDGE_QUIZ_SYSTEM_V1, QUIZ_GENERATION_SYSTEM_V1

logger = logging.getLogger(__name__)

JUDGE_RETRY_THRESHOLD = 4


class QuizPayload(BaseModel):
    """What the worker sends per item (planning.md 'Quiz Generation' flow)."""

    target_token: str
    type: str
    question_type: Literal["mcq", "translation"] = "mcq"
    meaning_note: str | None = None
    linguistic_metadata: dict | None = None
    user_note: str | None = None


class QuizQuestion(BaseModel):
    question_type: Literal["mcq", "translation"]
    prompt_text: str = Field(
        description="mcq: target-language sentence with ___ blank; "
        "translation: English sentence to translate"
    )
    choices: list[str] | None = Field(default=None, min_length=4, max_length=4)
    correct_index: int | None = Field(default=None, ge=0, le=3)
    expected_answer: str | None = None
    explanation: str
    tested_point: str

    @model_validator(mode="after")
    def fields_match_type(self) -> "QuizQuestion":
        if self.question_type == "mcq":
            if self.choices is None or self.correct_index is None:
                raise ValueError("mcq requires choices and correct_index")
            if len({c.strip().lower() for c in self.choices}) != 4:
                raise ValueError("choices must be 4 distinct options")
        else:
            if not self.expected_answer:
                raise ValueError("translation requires expected_answer")
        return self


class JudgeVerdict(BaseModel):
    target_alignment: int = Field(ge=1, le=5)
    linguistic_authenticity: int = Field(ge=1, le=5)
    distractor_validity: int = Field(ge=1, le=5)
    overall: int = Field(ge=1, le=5)
    rationale: str


def generate_quiz(
    payload: QuizPayload,
    language: str = "French",
    client: LLMClient | None = None,
    improvement_hint: str | None = None,
) -> QuizQuestion:
    client = client or LLMClient()
    user_content = json.dumps(payload.model_dump(), ensure_ascii=False)
    if improvement_hint:
        user_content += (
            f"\n\nA previous attempt was rejected by a quality judge for this "
            f"reason — avoid it: {improvement_hint}"
        )
    messages = [
        {"role": "system", "content": QUIZ_GENERATION_SYSTEM_V1.format(language=language)},
        {"role": "user", "content": user_content},
    ]
    return client.complete_structured(
        messages, QuizQuestion, purpose="quiz_generation", temperature=0.2
    )


def judge_quiz(
    payload: QuizPayload,
    quiz: QuizQuestion,
    language: str = "French",
    client: LLMClient | None = None,
) -> JudgeVerdict:
    client = client or LLMClient()
    judge_input = {"payload": payload.model_dump(), "generated": quiz.model_dump()}
    messages = [
        {"role": "system", "content": JUDGE_QUIZ_SYSTEM_V1.format(language=language)},
        {"role": "user", "content": json.dumps(judge_input, ensure_ascii=False)},
    ]
    return client.complete_structured(
        messages, JudgeVerdict, purpose="judge_quiz", temperature=0.0
    )


def generate_quiz_judged(
    payload: QuizPayload, language: str = "French", client: LLMClient | None = None
) -> tuple[QuizQuestion, JudgeVerdict]:
    """Generate -> judge -> at most ONE retry with the judge's rationale."""
    client = client or LLMClient()
    quiz = generate_quiz(payload, language, client)
    verdict = judge_quiz(payload, quiz, language, client)
    if verdict.overall >= JUDGE_RETRY_THRESHOLD:
        return quiz, verdict
    logger.warning(
        "quiz below judge threshold",
        extra={
            "event": "QUIZ_JUDGE_REJECTED",
            "target_token": payload.target_token,
            "scores": verdict.model_dump(),
            "quiz": quiz.model_dump(),
        },
    )
    retry = generate_quiz(payload, language, client, improvement_hint=verdict.rationale)
    retry_verdict = judge_quiz(payload, retry, language, client)
    if retry_verdict.overall >= verdict.overall:
        return retry, retry_verdict
    return quiz, verdict
