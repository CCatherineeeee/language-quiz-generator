"""Analysis Layer of the input pipeline (features.md P0).

Stage 1: spelling & grammar check. The checker only reports; it never silently
rewrites the user's input — the chat layer shows the correction and the user
confirms before anything is stored (confirm-first rule).

Stage 2: ambiguity check. is_ambiguous=true means one thing only: the pipeline
must short-circuit and ask the user. Resolution always comes from the user's
answer, never from the LLM guessing the most likely meaning.
"""

from pydantic import BaseModel, Field

from app.llm.client import LLMClient
from app.prompts import AMBIGUITY_SYSTEM_V1, INPUT_CHECK_SYSTEM_V3


class SpellingIssue(BaseModel):
    original: str = Field(description="The exact mistaken text as the user wrote it")
    corrected: str = Field(description="The corrected text")
    explanation: str = Field(
        description="One short English sentence a beginner can understand"
    )


class InputCheckResult(BaseModel):
    has_issues: bool
    corrected_input: str = Field(
        description="The full user message with only the mistakes fixed; "
        "identical to the input when has_issues is false"
    )
    issues: list[SpellingIssue] = []


class MeaningCandidate(BaseModel):
    meaning: str = Field(description="One distinct meaning, stated in English")
    example: str = Field(
        description="A short target-language example sentence showing this meaning"
    )


class AmbiguityResult(BaseModel):
    is_ambiguous: bool
    candidates: list[MeaningCandidate] = []
    clarification_question: str | None = Field(
        default=None,
        description="Ready-to-show English question listing the meanings; "
        "always offers 'or both?'",
    )


def check_ambiguity(
    text: str, language: str = "French", client: LLMClient | None = None
) -> AmbiguityResult:
    client = client or LLMClient()
    messages = [
        {"role": "system", "content": AMBIGUITY_SYSTEM_V1.format(language=language)},
        {"role": "user", "content": text},
    ]
    result = client.complete_structured(
        messages, AmbiguityResult, purpose="ambiguity_check", temperature=0.0
    )
    # Defensive symmetry with stage 1: an "ambiguous" verdict without at least
    # two distinct candidate meanings cannot be acted on — treat as unambiguous.
    if result.is_ambiguous and len(result.candidates) < 2:
        result.is_ambiguous = False
        result.candidates = []
        result.clarification_question = None
    return result


def check_input(
    text: str, language: str = "French", client: LLMClient | None = None
) -> InputCheckResult:
    client = client or LLMClient()
    messages = [
        {"role": "system", "content": INPUT_CHECK_SYSTEM_V3.format(language=language)},
        {"role": "user", "content": text},
    ]
    result = client.complete_structured(
        messages, InputCheckResult, purpose="input_check", temperature=0.0
    )
    # Observed failure mode (prompt_devlog: V2): the model sometimes emits
    # confirmation entries like "appris -> appris" on clean input. An issue
    # that changes nothing is not an issue.
    result.issues = [i for i in result.issues if i.original != i.corrected]
    if not result.issues and result.corrected_input == text:
        result.has_issues = False
    # Observed failure mode (prompt_devlog: V3): bare "soireé" came back
    # corrected but with has_issues=false and no issue entry. If the text
    # changed, there IS an issue — enforce consistency deterministically.
    if result.corrected_input.strip() != text.strip():
        result.has_issues = True
        if not result.issues:
            result.issues = [
                SpellingIssue(
                    original=text.strip(),
                    corrected=result.corrected_input.strip(),
                    explanation="Spelling corrected.",
                )
            ]
    return result
