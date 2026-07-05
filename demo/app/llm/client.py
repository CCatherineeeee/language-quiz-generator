"""LLMClient with provider fallback.

Tries each active provider in order. When one is out of quota / rate-limited
(or otherwise fails), it logs the call, posts an in-app chat notification
("switched from X to Y"), and moves to the next provider. Raises only when every
provider is exhausted.
"""
import json
import time

import httpx

from .providers import active_providers, Provider


class AllProvidersFailed(Exception):
    pass


# HTTP statuses that mean "this provider can't serve right now, try the next one".
_QUOTA_STATUSES = {429, 402}
_TRANSIENT_STATUSES = {500, 502, 503, 504}


def _is_quota(status: int, body: str) -> bool:
    if status in _QUOTA_STATUSES:
        return True
    low = body.lower()
    return any(s in low for s in ("quota", "rate limit", "rate_limit", "insufficient", "exhausted"))


class LLMClient:
    def __init__(self, log_call=None, notify=None):
        """log_call(provider, model, purpose, ok, error, latency_ms) -> None
        notify(kind, message) -> None  (used for the in-app chat feed)"""
        self.log_call = log_call or (lambda **k: None)
        self.notify = notify or (lambda kind, message: None)

    def _call_provider(self, p: Provider, messages, json_mode, temperature, timeout):
        url = f"{p.base_url}/chat/completions"
        payload = {
            "model": p.model,
            "messages": messages,
            "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {p.api_key}"}
        r = httpx.post(url, json=payload, headers=headers, timeout=timeout)
        if r.status_code != 200:
            raise httpx.HTTPStatusError(
                f"{r.status_code}: {r.text[:300]}", request=r.request, response=r
            )
        data = r.json()
        return data["choices"][0]["message"]["content"]

    def complete(self, messages, purpose="generation", json_mode=False,
                 temperature=0.7, timeout=60):
        providers = active_providers()
        if not providers:
            raise AllProvidersFailed(
                "No LLM providers have API keys set. Add at least GROQ_API_KEY to .env."
            )

        last_err = None
        for i, p in enumerate(providers):
            t0 = time.time()
            try:
                content = self._call_provider(p, messages, json_mode, temperature, timeout)
                self.log_call(provider=p.name, model=p.model, purpose=purpose,
                              ok=True, error=None, latency_ms=int((time.time() - t0) * 1000))
                # If we are not on the first provider, we recovered via fallback.
                return {"content": content, "provider": p.name, "model": p.model}
            except Exception as e:  # noqa: BLE001 - we explicitly want to fall through
                status = getattr(getattr(e, "response", None), "status_code", 0)
                body = getattr(getattr(e, "response", None), "text", str(e))
                self.log_call(provider=p.name, model=p.model, purpose=purpose,
                              ok=False, error=str(e)[:300],
                              latency_ms=int((time.time() - t0) * 1000))
                last_err = e

                nxt = providers[i + 1] if i + 1 < len(providers) else None
                if nxt is None:
                    self.notify("error",
                                f"⚠️ All LLM providers failed. Last error on "
                                f"'{p.name}': {str(e)[:120]}")
                    break
                if _is_quota(status, body):
                    self.notify("provider_switch",
                                f"🔁 '{p.name}' is out of quota / rate-limited. "
                                f"Switched to '{nxt.name}'.")
                else:
                    self.notify("provider_switch",
                                f"🔁 '{p.name}' failed ({status or 'error'}). "
                                f"Switched to '{nxt.name}'.")

        raise AllProvidersFailed(str(last_err))


def parse_json(content: str):
    """Tolerant JSON parse: strips ```json fences and leading/trailing prose."""
    s = content.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1]
        if s.startswith("json"):
            s = s[4:]
        s = s.strip().rstrip("`").strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        start = s.find("{")
        end = s.rfind("}")
        if start != -1 and end != -1:
            return json.loads(s[start:end + 1])
        raise
