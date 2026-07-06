from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Loaded from environment variables / project-root .env (see decision log #5, #7)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    # Single shared secret for the owner account (decision log #5). No password auth.
    owner_secret: str = "change-me-in-env"

    # LLM provider keys; any subset may be set — the fallback chain skips missing ones.
    groq_api_key: str | None = None
    gemini_api_key: str | None = None
    openrouter_api_key: str | None = None


settings = Settings()
