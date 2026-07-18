"""Learn-tab state machine + Quiz-tab helpers, all through FakeLLMs."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import GlobalDictionary, PendingQuiz, User, UserMasteryMatrix
from app.services.analysis import AmbiguityResult, InputCheckResult
from app.services.extraction import ExtractionResult
from app.ui import ChatDeps, answers_from_values, chat_step, fetch_open_quizzes

CLEAN = InputCheckResult(has_issues=False, corrected_input="I learned soirée")
TYPO = InputCheckResult(
    has_issues=True,
    corrected_input="I learned soirée",
    issues=[{"original": "soireé", "corrected": "soirée",
             "explanation": "accent order"}],
)
UNAMBIGUOUS = AmbiguityResult(is_ambiguous=False)
AMBIGUOUS = AmbiguityResult(
    is_ambiguous=True,
    candidates=[
        {"meaning": "evening", "example": "La soirée était longue."},
        {"meaning": "evening party", "example": "On organise une soirée."},
    ],
    clarification_question="Do you mean evening, evening party, or both?",
)
EXTRACTED = ExtractionResult(
    items=[{"token": "soirée", "type": "root_noun", "meaning_note": "evening party",
            "linguistic_metadata": {"gender": "feminine"}, "parent_token": None}],
    suggestions=[{"token": "soir", "type": "root_noun", "relation": "base noun",
                  "parent_token": None}],
)


class ScriptedLLM:
    """Returns each schema's scripted result; the UI never sees a real LLM."""

    def __init__(self, **by_schema_name):
        self.by_schema_name = by_schema_name

    def complete_structured(self, messages, schema, **kwargs):
        return self.by_schema_name[schema.__name__]


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


def _deps(factory, **results):
    return ChatDeps(session_factory=factory, client=ScriptedLLM(**results))


def test_clean_input_flows_to_save_confirmation(factory):
    deps = _deps(
        factory,
        InputCheckResult=CLEAN,
        AmbiguityResult=UNAMBIGUOUS,
        ExtractionResult=EXTRACTED,
    )
    state = {}
    reply = chat_step("I learned soirée", state, 1, deps)
    assert state["step"] == "confirm_save"
    assert "soirée" in reply and "Save?" in reply and "soir (base noun)" in reply


def test_typo_asks_confirmation_then_proceeds(factory):
    deps = _deps(
        factory,
        InputCheckResult=TYPO,
        AmbiguityResult=UNAMBIGUOUS,
        ExtractionResult=EXTRACTED,
    )
    state = {}
    reply = chat_step("I learned soireé", state, 1, deps)
    assert state["step"] == "confirm_correction"
    assert "soireé -> soirée" in reply

    reply = chat_step("yes", state, 1, deps)
    assert state["step"] == "confirm_save"


def test_ambiguity_short_circuits_and_user_answer_resolves(factory):
    deps = _deps(
        factory,
        InputCheckResult=CLEAN,
        AmbiguityResult=AMBIGUOUS,
        ExtractionResult=EXTRACTED,
    )
    state = {}
    reply = chat_step("I learned soirée", state, 1, deps)
    assert state["step"] == "resolve_ambiguity"
    assert reply == AMBIGUOUS.clarification_question

    reply = chat_step("evening party", state, 1, deps)
    assert state["step"] == "confirm_save"


def test_yes_saves_and_returns_to_idle(factory):
    deps = _deps(
        factory,
        InputCheckResult=CLEAN,
        AmbiguityResult=UNAMBIGUOUS,
        ExtractionResult=EXTRACTED,
    )
    state = {}
    chat_step("I learned soirée", state, 1, deps)
    reply = chat_step("yes", state, 1, deps)
    assert "Saved" in reply and "quiz" in reply.lower()
    assert "step" not in state  # back to idle
    with factory() as s:
        tokens = s.scalars(select(GlobalDictionary.token)).all()
        assert tokens == ["soirée"]  # suggestion NOT saved without yes+1


def test_yes_plus_picks_saves_suggestions_too(factory):
    deps = _deps(
        factory,
        InputCheckResult=CLEAN,
        AmbiguityResult=UNAMBIGUOUS,
        ExtractionResult=EXTRACTED,
    )
    state = {}
    chat_step("I learned soirée", state, 1, deps)
    chat_step("yes+1", state, 1, deps)
    with factory() as s:
        tokens = set(s.scalars(select(GlobalDictionary.token)).all())
        assert tokens == {"soirée", "soir"}
        assert len(s.scalars(select(UserMasteryMatrix)).all()) == 2


def test_no_discards_everything(factory):
    deps = _deps(
        factory,
        InputCheckResult=CLEAN,
        AmbiguityResult=UNAMBIGUOUS,
        ExtractionResult=EXTRACTED,
    )
    state = {}
    chat_step("I learned soirée", state, 1, deps)
    reply = chat_step("no", state, 1, deps)
    assert "Discarded" in reply
    with factory() as s:
        assert s.scalars(select(GlobalDictionary)).all() == []


def test_gibberish_at_save_step_reprompts_without_losing_state(factory):
    deps = _deps(
        factory,
        InputCheckResult=CLEAN,
        AmbiguityResult=UNAMBIGUOUS,
        ExtractionResult=EXTRACTED,
    )
    state = {}
    chat_step("I learned soirée", state, 1, deps)
    reply = chat_step("maybe??", state, 1, deps)
    assert "yes" in reply and state["step"] == "confirm_save"


def test_fetch_open_quizzes_and_answer_mapping(factory):
    q = {
        "question_type": "mcq",
        "prompt_text": "La ___ était réussie.",
        "choices": ["soirée", "soir", "nuit", "journée"],
        "correct_index": 0,
        "expected_answer": None,
        "explanation": "feminine noun fits",
        "tested_point": "soirée",
    }
    with factory() as s:
        s.add(PendingQuiz(
            user_id=1,
            quiz_data={"questions": [{"entity_id": 1, "question": q,
                                      "judge_overall": 5}]},
            entity_ids=[1],
            created_at=datetime.now(UTC),
        ))
        s.commit()

    quizzes = fetch_open_quizzes(1, factory)
    assert len(quizzes) == 1 and quizzes[0]["questions"][0]["question"] == q

    answers = answers_from_values(quizzes[0]["questions"], ["soirée"])
    assert answers[0].chosen_index == 0

    with pytest.raises(ValueError):
        answers_from_values(quizzes[0]["questions"], [None])  # unanswered


def test_mounted_app_serves_gradio_and_api():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    assert client.get("/health").status_code == 200  # API still wins its routes
    assert client.get("/").status_code == 200  # Gradio page at the root
