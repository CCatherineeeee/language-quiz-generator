"""Free-tier LLM provider registry (ported from demo/, decision: fallback chain).

All providers expose an OpenAI-compatible /chat/completions endpoint, so one code
path in client.py serves every provider. Order matters: the chain tries top to
bottom. To add a provider: append an entry and add its key field to Settings.
"""

from dataclasses import dataclass

from app.config import settings


@dataclass(frozen=True)
class Provider:
    name: str            # display name
    settings_field: str  # Settings attribute holding the API key
    base_url: str        # OpenAI-compatible base (no trailing /chat/completions)
    model: str           # default model id

    @property
    def api_key(self) -> str | None:
        return getattr(settings, self.settings_field, None)

    @property
    def active(self) -> bool:
        return bool(self.api_key)


PROVIDERS: list[Provider] = [
    Provider(
        name="groq",
        settings_field="groq_api_key",
        base_url="https://api.groq.com/openai/v1",
        model="llama-3.3-70b-versatile",
    ),
    Provider(
        name="gemini",
        settings_field="gemini_api_key",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        model="gemini-2.0-flash",
    ),
    Provider(
        name="openrouter",
        settings_field="openrouter_api_key",
        base_url="https://openrouter.ai/api/v1",
        model="meta-llama/llama-3.3-70b-instruct:free",
    ),
]


def active_providers() -> list[Provider]:
    return [p for p in PROVIDERS if p.active]
