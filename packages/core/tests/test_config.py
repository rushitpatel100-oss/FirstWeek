import os

import pytest

from firstweek_core.config import Settings


def test_blank_keys_in_env_file_mean_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "")
    settings = Settings(_env_file=None)
    assert settings.anthropic_api_key is None
    assert settings.tracing_enabled is False


def test_export_credentials_fills_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "LANGFUSE_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings(_env_file=None, anthropic_api_key="sk-test", openai_api_key=None)

    settings.export_credentials()

    assert os.environ["ANTHROPIC_API_KEY"] == "sk-test"
    assert "OPENAI_API_KEY" not in os.environ
    assert os.environ["LANGFUSE_BASE_URL"] == "https://cloud.langfuse.com"


def test_existing_environment_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-shell")
    Settings(_env_file=None, anthropic_api_key="from-dotenv").export_credentials()
    assert os.environ["ANTHROPIC_API_KEY"] == "from-shell"
