"""Linguistic meta-extractor (features.md P0, pipeline stage 3).

Turns a checked, disambiguated report into storage-ready items plus
related-form suggestions. Output shape matches the storage transaction spec
(progress.md): token / type / meaning_note / linguistic_metadata / parent.
Confirm-first: nothing here is saved — the chat layer shows items and
suggestions for the user to confirm.
"""

import json

from pydantic import BaseModel, Field

from app.llm.client import LLMClient
from app.prompts import EXTRACTION_SYSTEM_V1


class ExtractedItem(BaseModel):
    token: str
    type: str = Field(description="root_noun, root_verb, conjugation, phrase, ...")
    meaning_note: str | None = None
    linguistic_metadata: dict = Field(default_factory=dict)
    parent_token: str | None = None


class RelatedSuggestion(BaseModel):
    token: str
    type: str
    relation: str = Field(description='e.g. "plural", "nous form, present tense"')
    parent_token: str | None = None


class ExtractionResult(BaseModel):
    items: list[ExtractedItem]
    suggestions: list[RelatedSuggestion] = Field(default_factory=list, max_length=5)


def extract_knowledge(
    text: str,
    resolved_meaning: str | None = None,
    language: str = "French",
    client: LLMClient | None = None,
) -> ExtractionResult:
    client = client or LLMClient()
    payload = {"message": text, "resolved_meaning": resolved_meaning}
    messages = [
        {"role": "system", "content": EXTRACTION_SYSTEM_V1.format(language=language)},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    result = client.complete_structured(
        messages, ExtractionResult, purpose="extraction", temperature=0.0
    )
    # A suggestion duplicating an extracted item is noise (prompt forbids it,
    # code guarantees it).
    item_tokens = {i.token.strip().lower() for i in result.items}
    result.suggestions = [
        s for s in result.suggestions if s.token.strip().lower() not in item_tokens
    ]
    return result
