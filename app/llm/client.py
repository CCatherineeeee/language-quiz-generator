"""LLM client: provider fallback + schema-constrained structured outputs.

Fallback (ported from demo/): try each active provider in order; on quota or
transient failure move to the next; raise only when all are exhausted.

Structured outputs (decision log #2): `complete_structured` binds the call to a
Pydantic model. JSON mode + the schema in the prompt steer the model; Pydantic
validation is the actual correctness guarantee, with one repair retry that feeds
the validation error back to the model.
"""

import json
import logging
import time

import httpx
from pydantic import BaseModel, ValidationError

from .providers import Provider, active_providers

logger = logging.getLogger("llm")


class AllProvidersFailed(Exception):
    pass


class StructuredOutputError(Exception):
    """The LLM answered, but never produced JSON matching the schema."""


_QUOTA_STATUSES = {429, 402}


def _is_quota(status: int, body: str) -> bool:
    if status in _QUOTA_STATUSES:
        return True
    low = body.lower()
    return any(
        s in low for s in ("quota", "rate limit", "rate_limit", "insufficient", "exhausted")
    )


def _is_transient(status: int, body: str) -> bool:
    """Provider hiccups worth one same-provider retry (never quota errors).

    Observed live (prompt_devlog V3): Groq JSON mode intermittently dies with
    400 json_validate_failed ("max completion tokens reached before generating
    a valid document") — the model looped; the next attempt usually succeeds.
    """
    if status >= 500:
        return True
    return "json_validate_failed" in body.lower()


def parse_json(content: str):
    """Tolerant JSON parse: strips ```json fences and surrounding prose."""
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
            return json.loads(s[start : end + 1])
        raise


class LLMClient:
    def __init__(self, log_call=None, notify=None):
        """log_call(provider, model, purpose, ok, error, latency_ms) -> None
        notify(kind, message) -> None (surfaced in the chat UI)."""
        self.log_call = log_call or self._default_log
        self.notify = notify or (lambda kind, message: logger.info("[%s] %s", kind, message))

    @staticmethod
    def _default_log(**kw):
        logger.info(json.dumps({"event": "LLM_CALL", **kw}))

    def _call_provider(self, p: Provider, messages, json_mode, temperature, timeout):
        payload = {"model": p.model, "messages": messages, "temperature": temperature}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        r = httpx.post(
            f"{p.base_url}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {p.api_key}"},
            timeout=timeout,
        )
        if r.status_code != 200:
            raise httpx.HTTPStatusError(
                f"{r.status_code}: {r.text[:300]}", request=r.request, response=r
            )
        return r.json()["choices"][0]["message"]["content"]

    def complete(self, messages, purpose="generation", json_mode=False,
                 temperature=0.7, timeout=60):
        providers = active_providers()
        if not providers:
            raise AllProvidersFailed(
                "No LLM providers have API keys set. Add at least GROQ_API_KEY to .env."
            )

        last_err = None
        for i, p in enumerate(providers):
            # Two attempts per provider, but the second only for transient
            # failures (never quota — those go straight to the fallback).
            for attempt in (1, 2):
                t0 = time.time()
                try:
                    content = self._call_provider(p, messages, json_mode, temperature, timeout)
                    self.log_call(provider=p.name, model=p.model, purpose=purpose,
                                  ok=True, error=None,
                                  latency_ms=int((time.time() - t0) * 1000))
                    return {"content": content, "provider": p.name, "model": p.model}
                except Exception as e:  # noqa: BLE001 - retry or fall through
                    status = getattr(getattr(e, "response", None), "status_code", 0)
                    body = getattr(getattr(e, "response", None), "text", str(e))
                    self.log_call(provider=p.name, model=p.model, purpose=purpose,
                                  ok=False, error=str(e)[:300],
                                  latency_ms=int((time.time() - t0) * 1000))
                    last_err = e
                    if attempt == 1 and not _is_quota(status, body) and _is_transient(status, body):
                        self.notify("transient_retry",
                                    f"'{p.name}' transient failure ({status}). Retrying once.")
                        continue
                    nxt = providers[i + 1] if i + 1 < len(providers) else None
                    if nxt is None:
                        self.notify("error", f"All LLM providers failed. Last error on "
                                             f"'{p.name}': {str(e)[:120]}")
                    else:
                        reason = "is out of quota / rate-limited" if _is_quota(status, body) \
                            else f"failed ({status or 'error'})"
                        self.notify("provider_switch",
                                    f"'{p.name}' {reason}. Switched to '{nxt.name}'.")
                    break

        raise AllProvidersFailed(str(last_err))

    def complete_structured[T: BaseModel](
        self, messages: list[dict], schema: type[T],
        purpose: str = "generation", temperature: float = 0.2, timeout: int = 60,
    ) -> T:
        """Call the LLM and return a validated instance of `schema`.

        One repair retry: if validation fails, the error is sent back so the
        model can fix its own output. Beyond that, StructuredOutputError.
        """
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        constrained = [
            *messages,
            {"role": "system",
             "content": "Respond with a single JSON object matching this JSON Schema "
                        f"exactly. No prose, no markdown fences.\n{schema_json}"},
        ]
        last_error = None
        for _attempt in range(2):
            result = self.complete(constrained, purpose=purpose, json_mode=True,
                                   temperature=temperature, timeout=timeout)
            try:
                return schema.model_validate(parse_json(result["content"]))
            except (ValidationError, json.JSONDecodeError) as e:
                last_error = e
                constrained = [
                    *constrained,
                    {"role": "assistant", "content": result["content"]},
                    {"role": "user",
                     "content": f"That response failed validation:\n{e}\n"
                                "Return only the corrected JSON object."},
                ]
        raise StructuredOutputError(str(last_error))
