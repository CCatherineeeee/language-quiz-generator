"""Analysis Layer of the input pipeline (features.md P0).

Stage 1: spelling & grammar check. The checker only reports; it never silently
rewrites the user's input — the chat layer shows the correction and the user
confirms before anything is stored (confirm-first rule).
"""

from pydantic import BaseModel, Field

from app.llm.client import LLMClient
from app.prompts import INPUT_CHECK_SYSTEM_V2


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


def check_input(
    text: str, language: str = "French", client: LLMClient | None = None
) -> InputCheckResult:
    client = client or LLMClient()
    messages = [
        {"role": "system", "content": INPUT_CHECK_SYSTEM_V2.format(language=language)},
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
    return result
