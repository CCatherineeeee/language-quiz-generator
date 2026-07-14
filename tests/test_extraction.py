from fastapi.testclient import TestClient

from app.main import MAX_INPUT_CHARS, app
from app.services import extraction
from app.services.extraction import extract_knowledge

client = TestClient(app)


class FakeLLM:
    def __init__(self, payload: dict):
        self.payload = payload
        self.calls = []

    def complete_structured(self, messages, schema, **kwargs):
        self.calls.append({"messages": messages, "schema": schema, **kwargs})
        return schema.model_validate(self.payload)


RESULT = {
    "items": [
        {
            "token": "je parle",
            "type": "conjugation",
            "meaning_note": None,
            "linguistic_metadata": {"infinitive": "parler", "tense": "present"},
            "parent_token": "parler",
        }
    ],
    "suggestions": [
        {"token": "parler", "type": "root_verb", "relation": "infinitive", "parent_token": None},
        # duplicates the extracted item -> must be dropped by the code guard
        {"token": "Je Parle ", "type": "conjugation", "relation": "present",
         "parent_token": "parler"},
    ],
}


def test_extract_returns_items_and_dedupes_suggestions():
    fake = FakeLLM(RESULT)
    r = extract_knowledge("I learned je parle", client=fake)
    assert r.items[0].parent_token == "parler"
    assert [s.token for s in r.suggestions] == ["parler"]


def test_resolved_meaning_is_sent_to_llm():
    fake = FakeLLM(RESULT)
    extract_knowledge("I learned soirée", resolved_meaning="an evening party", client=fake)
    assert "an evening party" in fake.calls[0]["messages"][-1]["content"]


def test_extract_endpoint(monkeypatch):
    monkeypatch.setattr(extraction, "LLMClient", lambda *a, **k: FakeLLM(RESULT))
    r = client.post("/api/input/extract", json={"text": "I learned je parle"})
    assert r.status_code == 200
    assert r.json()["items"][0]["token"] == "je parle"


def test_extract_endpoint_rejects_oversized():
    r = client.post("/api/input/extract", json={"text": "a" * (MAX_INPUT_CHARS + 1)})
    assert r.status_code == 413
