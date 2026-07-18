"""Quiz submission flow: grade -> SM-2 update -> quiz COMPLETED.

Shape of the flow (the four-pillars rules it follows):
1. Read the quiz and check it isn't already COMPLETED — then CLOSE the
   transaction before grading, because typed answers may need an LLM call
   and a DB transaction must never stay open across a network call.
2. Grade every answer (mcq: deterministic; typed: exact-match fast path,
   LLM otherwise).
3. One write transaction: re-check COMPLETED under a row lock (two
   simultaneous submits of the same quiz — a double-click — must not both
   advance SM-2), apply every item's review, flip the quiz to COMPLETED.
"""

from datetime import datetime

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.llm.client import LLMClient
from app.models import PendingQuiz, QuizStatus
from app.services.grading import GradeResult, grade_mcq, grade_typed
from app.services.scheduler import apply_review


class QuizAlreadyCompletedError(Exception):
    pass


class AnswerMismatchError(ValueError):
    pass


class SubmittedAnswer(BaseModel):
    chosen_index: int | None = Field(default=None, ge=0, le=3)  # mcq
    typed_answer: str | None = None  # translation


class QuestionOutcome(BaseModel):
    entity_id: int
    is_correct: bool
    quality: int
    feedback: str
    interval_days: int
    next_review_date: datetime


class SubmitResult(BaseModel):
    quiz_id: int
    outcomes: list[QuestionOutcome]


def _grade_one(question: dict, answer: SubmittedAnswer, client) -> GradeResult:
    if question["question_type"] == "mcq":
        if answer.chosen_index is None:
            raise AnswerMismatchError("an mcq question needs chosen_index")
        return grade_mcq(
            answer.chosen_index, question["correct_index"], question["explanation"]
        )
    if not answer.typed_answer:
        raise AnswerMismatchError("a translation question needs typed_answer")
    return grade_typed(
        question["prompt_text"],
        question["expected_answer"],
        answer.typed_answer,
        client=client,
    )


def submit_quiz(
    session: Session,
    quiz_id: int,
    answers: list[SubmittedAnswer],
    client: LLMClient | None = None,
    now: datetime | None = None,
) -> SubmitResult:
    with session.begin():
        quiz = session.get(PendingQuiz, quiz_id)
        if quiz is None:
            raise LookupError(f"no quiz {quiz_id}")
        if quiz.status == QuizStatus.COMPLETED:
            raise QuizAlreadyCompletedError(f"quiz {quiz_id} was already submitted")
        questions = [q["question"] for q in quiz.quiz_data["questions"]]
        entity_ids = [q["entity_id"] for q in quiz.quiz_data["questions"]]
        user_id = quiz.user_id
    if len(answers) != len(questions):
        raise AnswerMismatchError(
            f"quiz has {len(questions)} questions, got {len(answers)} answers"
        )

    # No transaction open here: grading may call the LLM.
    grades = [_grade_one(q, a, client) for q, a in zip(questions, answers, strict=True)]

    with session.begin():
        quiz = session.get(PendingQuiz, quiz_id, with_for_update=True)
        if quiz.status == QuizStatus.COMPLETED:  # lost a double-submit race
            raise QuizAlreadyCompletedError(f"quiz {quiz_id} was already submitted")
        outcomes = []
        for entity_id, grade in zip(entity_ids, grades, strict=True):
            state = apply_review(session, user_id, entity_id, grade.quality, now)
            outcomes.append(
                QuestionOutcome(
                    entity_id=entity_id,
                    is_correct=grade.is_correct,
                    quality=grade.quality,
                    feedback=grade.feedback,
                    interval_days=state.interval_days,
                    next_review_date=state.next_review_date,
                )
            )
        quiz.status = QuizStatus.COMPLETED
    return SubmitResult(quiz_id=quiz_id, outcomes=outcomes)
