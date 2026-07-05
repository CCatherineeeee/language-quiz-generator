"""Free-tier LLM provider registry.

All providers here expose an OpenAI-compatible /chat/completions endpoint, so one
code path in client.py serves every provider. To add a new free provider later
(e.g. OpenRouter, Cerebras), append one Provider entry below and set its API key
in .env. Order matters: the fallback chain tries providers top to bottom.
"""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Provider:
    name: str          # display name
    env_key: str       # env var holding the API key
    base_url: str      # OpenAI-compatible base (no trailing /chat/completions)
    model: str         # default model id

    @property
    def api_key(self) -> str | None:
        return os.environ.get(self.env_key)

    @property
    def active(self) -> bool:
        return bool(self.api_key)


# Ordered fallback chain. Groq first (you have the key), then Gemini.
# Uncomment / append more as you add keys — nothing else needs to change.
PROVIDERS: list[Provider] = [
    Provider(
        name="groq",
        env_key="GROQ_API_KEY",
        base_url="https://api.groq.com/openai/v1",
        model="llama-3.3-70b-versatile",
    ),
    Provider(
        name="gemini",
        env_key="GEMINI_API_KEY",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        model="gemini-2.0-flash",
    ),
    # Provider(
    #     name="openrouter",
    #     env_key="OPENROUTER_API_KEY",
    #     base_url="https://openrouter.ai/api/v1",
    #     model="meta-llama/llama-3.3-70b-instruct:free",
    # ),
    # Provider(
    #     name="cerebras",
    #     env_key="CEREBRAS_API_KEY",
    #     base_url="https://api.cerebras.ai/v1",
    #     model="llama-3.3-70b",
    # ),
]


def active_providers() -> list[Provider]:
    return [p for p in PROVIDERS if p.active]
