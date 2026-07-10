from fastapi.testclient import TestClient

from app.main import MAX_INPUT_CHARS, app
from app.services import analysis
from app.services.analysis import InputCheckResult, SpellingIssue, check_input

client = TestClient(app)


class FakeLLM:
    """Stands in for LLMClient: returns a canned payload, records the call."""

    def __init__(self, payload: dict):
        self.payload = payload
        self.calls = []

    def complete_structured(self, messages, schema, **kwargs):
        self.calls.append({"messages": messages, "schema": schema, **kwargs})
        return schema.model_validate(self.payload)


CORRECTION = {
    "has_issues": True,
    "corrected_input": "j'ai appris le mot soirée",
    "issues": [
        {
            "original": "soireé",
            "corrected": "soirée",
            "explanation": "The accent belongs on the first e: soirée.",
        }
    ],
}

CLEAN = {"has_issues": False, "corrected_input": "j'ai appris le mot soirée", "issues": []}


def test_check_input_returns_corrections():
    fake = FakeLLM(CORRECTION)
    result = check_input("j'ai appris le mot soireé", client=fake)
    assert result.has_issues
    assert result.corrected_input == "j'ai appris le mot soirée"
    assert result.issues[0] == SpellingIssue(
        original="soireé",
        corrected="soirée",
        explanation="The accent belongs on the first e: soirée.",
    )


def test_check_input_sends_user_text_and_zero_temperature():
    fake = FakeLLM(CLEAN)
    check_input("j'ai appris le mot soirée", client=fake)
    call = fake.calls[0]
    assert call["messages"][-1] == {"role": "user", "content": "j'ai appris le mot soirée"}
    assert call["schema"] is InputCheckResult
    assert call["temperature"] == 0.0


def test_noop_issues_are_filtered():
    # Observed live (prompt_devlog V2): confirmation entries on clean input.
    fake = FakeLLM(
        {
            "has_issues": False,
            "corrected_input": "j'ai appris le mot soirée",
            "issues": [
                {
                    "original": "appris",
                    "corrected": "appris",
                    "explanation": "This conjugation is correct.",
                }
            ],
        }
    )
    result = check_input("j'ai appris le mot soirée", client=fake)
    assert result.issues == []
    assert result.has_issues is False


def test_endpoint_returns_check_result(monkeypatch):
    monkeypatch.setattr(
        analysis, "LLMClient", lambda *a, **k: FakeLLM(CORRECTION)
    )
    r = client.post("/api/input/check", json={"text": "j'ai appris le mot soireé"})
    assert r.status_code == 200
    body = r.json()
    assert body["has_issues"] is True
    assert body["issues"][0]["corrected"] == "soirée"


def test_endpoint_rejects_oversized_input():
    r = client.post("/api/input/check", json={"text": "a" * (MAX_INPUT_CHARS + 1)})
    assert r.status_code == 413


def test_endpoint_rejects_empty_input():
    r = client.post("/api/input/check", json={"text": ""})
    assert r.status_code == 422
