import httpx
import pytest

from app.llm.client import AllProvidersFailed, LLMClient
from app.llm.providers import Provider


def _fake_provider():
    return Provider(name="fake", settings_field="groq_api_key", base_url="http://x", model="m")


def _error(status: int, body: str) -> httpx.HTTPStatusError:
    resp = httpx.Response(status, text=body, request=httpx.Request("POST", "http://x"))
    return httpx.HTTPStatusError(f"{status}: {body}", request=resp.request, response=resp)


TRANSIENT = _error(400, '{"error": {"code": "json_validate_failed"}}')
QUOTA = _error(429, "rate limit exceeded")


class Script:
    """Scripted _call_provider: raises/returns per queued step."""

    def __init__(self, steps):
        self.steps = list(steps)
        self.calls = 0

    def __call__(self, *a, **k):
        self.calls += 1
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def _client_with(monkeypatch, script, providers):
    client = LLMClient()
    monkeypatch.setattr(client, "_call_provider", script)
    monkeypatch.setattr("app.llm.client.active_providers", lambda: providers)
    return client


def test_transient_failure_retries_same_provider_once(monkeypatch):
    script = Script([TRANSIENT, "ok"])
    client = _client_with(monkeypatch, script, [_fake_provider()])
    result = client.complete([{"role": "user", "content": "hi"}])
    assert result["content"] == "ok"
    assert script.calls == 2


def test_transient_failure_retries_at_most_once(monkeypatch):
    script = Script([TRANSIENT, TRANSIENT])
    client = _client_with(monkeypatch, script, [_fake_provider()])
    with pytest.raises(AllProvidersFailed):
        client.complete([{"role": "user", "content": "hi"}])
    assert script.calls == 2


def test_quota_failure_skips_retry_and_falls_through(monkeypatch):
    script = Script([QUOTA, "from-fallback"])
    providers = [_fake_provider(), _fake_provider()]
    client = _client_with(monkeypatch, script, providers)
    result = client.complete([{"role": "user", "content": "hi"}])
    assert result["content"] == "from-fallback"
    assert script.calls == 2  # one per provider, no same-provider retry
