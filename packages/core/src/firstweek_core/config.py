"""Typed settings, read from environment variables or a local .env file."""

import os
from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Infrastructure
    database_url: str = "postgresql+psycopg://firstweek:firstweek@localhost:5432/firstweek"
    redis_url: str = "redis://localhost:6379/0"
    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "firstweek-main"

    # Model providers
    anthropic_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None  # free tier: https://aistudio.google.com/apikey
    groq_api_key: SecretStr | None = None  # free tier, a second source: https://console.groq.com

    # Shared secret between the web app and the API. When set, the API trusts the client address
    # the web app forwards (the web app is the API's only client in production).
    internal_api_key: SecretStr | None = None

    # Model routing: LiteLLM model strings per tier
    model_frontier: str = "anthropic/claude-opus-5-5"
    model_mid: str = "anthropic/claude-sonnet-5-5"
    model_small: str = "anthropic/claude-haiku-5-5"
    model_judge: str = "gemini/gemini-3.6-flash"  # free tier; not Claude, so it can judge it
    # Tried in order when the free model is overloaded (503) or rate limited (429). Free only:
    # a paid tier never silently switches to another model.
    model_judge_fallbacks: list[str] = ["gemini/gemini-3.8-flash"]
    # Added last to the free chain when GROQ_API_KEY is set (8K tokens a minute: fine for chat,
    # tight for long reviews). A different provider, so one provider's daily cap does not stop us.
    model_groq: str = "groq/openai/gpt-oss-120b"
    # A free model on this machine through Ollama, e.g. "ollama/qwen2.5-coder:7b". When set it
    # is tried first for the judge tier: no daily limit, no key, no cost. The free hosted models
    # stay behind it as fallbacks.
    model_local: str = ""
    ollama_api_base: str = "http://localhost:11434"
    ollama_num_ctx: int = 12288  # Ollama's own default (a few thousand) silently cuts long prompts
    # "local/<name>" runs a free open-source model on this machine (ADR 0012); any other
    # value is a LiteLLM embedding model string such as "openai/text-embedding-3-small".
    model_embedding: str = "local/BAAI/bge-small-en-v1.5"
    model_cache_dir: str = "~/.cache/firstweek/models"

    # Budgets
    default_budget_usd: float = 2.0

    # Daily research: the worker keeps a Temporal schedule that collects and analyses every
    # golden role. Off in CI. Times are in research_daily_timezone.
    research_daily_enabled: bool = True
    research_daily_cron: str = "17 7 * * *"
    research_daily_timezone: str = "Europe/London"
    research_budget_usd_per_role: float = 1.0

    # Tracing
    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_base_url: str = "https://cloud.langfuse.com"

    # Research sources
    adzuna_app_id: str | None = None
    adzuna_app_key: SecretStr | None = None
    firecrawl_api_key: SecretStr | None = None

    # Code sandbox (ADR 0017): Docker on this machine in development, E2B for demos and evals
    sandbox_backend: Literal["docker", "e2b"] = "docker"
    sandbox_image: str = "firstweek-sandbox:py"
    e2b_api_key: SecretStr | None = None
    # Which model tier designs and builds simulation projects (ADR 0020). `judge` is the free
    # Gemini model; the gate retries what it gets wrong. Set SIMULATION_TIER=mid for Claude.
    simulation_tier: Literal["small", "mid", "frontier", "judge"] = "judge"
    # Generated project material (ADR 0019); an object store replaces this when we deploy
    artifacts_dir: str = "var/artifacts"

    @field_validator(
        "anthropic_api_key",
        "openai_api_key",
        "gemini_api_key",
        "groq_api_key",
        "internal_api_key",
        "langfuse_public_key",
        "langfuse_secret_key",
        "adzuna_app_id",
        "adzuna_app_key",
        "firecrawl_api_key",
        "e2b_api_key",
        mode="before",
    )
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        """`KEY=` in .env means 'not set', not an empty key."""
        return None if value == "" else value

    @property
    def has_judge_key(self) -> bool:
        """Whether any free provider is set up for the judge tier."""
        return (
            self.gemini_api_key is not None
            or self.groq_api_key is not None
            or bool(self.model_local)
        )

    def judge_fallbacks(self) -> list[str]:
        """Free models tried after the judge model, in order. Groq joins when its key is set."""
        extra = [self.model_groq] if self.groq_api_key is not None else []
        first = [self.model_judge] if self.model_local else []
        return [
            *first,
            *self.model_judge_fallbacks,
            *(m for m in extra if m not in self.model_judge_fallbacks),
        ]

    @property
    def tracing_enabled(self) -> bool:
        return self.langfuse_public_key is not None and self.langfuse_secret_key is not None

    def export_credentials(self) -> None:
        """LiteLLM and Langfuse read credentials from the process environment.

        Settings can come from .env, which does not touch os.environ, so copy them across.
        Values already in the environment win.
        """
        secrets = {
            "ANTHROPIC_API_KEY": self.anthropic_api_key,
            "OPENAI_API_KEY": self.openai_api_key,
            "GEMINI_API_KEY": self.gemini_api_key,
            "GROQ_API_KEY": self.groq_api_key,
            "LANGFUSE_PUBLIC_KEY": self.langfuse_public_key,
            "LANGFUSE_SECRET_KEY": self.langfuse_secret_key,
        }
        for name, value in secrets.items():
            if value is not None:
                os.environ.setdefault(name, value.get_secret_value())
        os.environ.setdefault("LANGFUSE_BASE_URL", self.langfuse_base_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()
