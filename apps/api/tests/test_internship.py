"""The internship endpoints: public script only, in-character chat, supervisor review."""

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_reports import _clean
from test_workspace import SECRET, FakeRunner, Prompts, world

from firstweek_api import internship as api
from firstweek_api import workspace as wsapi
from firstweek_api.main import app
from firstweek_api.skill_gap import Limiter
from firstweek_core.config import Settings
from firstweek_core.llm import BudgetRegistry, LLMGateway
from firstweek_core.llm.tracing import NoopTracer
from firstweek_simulation import demo_internship
from firstweek_simulation import internship as work
from firstweek_simulation import workspace as ws

__all__ = ["_clean", "world"]

client = TestClient(app)
PERSONA = "PRIVATE-PERSONA-TEXT"
VERDICT = {
    "summary": "A solid first week with one metric fixed and one gap left open.",
    "skills": [{"skill_id": "python", "score": 3, "evidence": "Small, correct change to total."}],
    "went_well": ["Fixed the total"],
    "to_work_on": ["Add a regression test"],
    "next_step": "Write a test that fails on the old total.",
}


class Replies(Prompts):
    """Plain text for chat, JSON for the structured verdict."""

    async def __call__(self, **kwargs: Any) -> SimpleNamespace:
        self.messages.append(kwargs["messages"])
        content = (
            json.dumps(VERDICT) if kwargs.get("response_format") else "Look at how total is built."
        )
        return SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content=content), finish_reason="stop")
            ],
            usage=SimpleNamespace(prompt_tokens=300, completion_tokens=60),
        )


@pytest.fixture
def team(
    world: tuple[FakeRunner, Prompts], monkeypatch: pytest.MonkeyPatch
) -> tuple[FakeRunner, Replies]:
    runner, _ = world
    root = Path(wsapi.get_settings().artifacts_dir)
    project = ws.approved_project("genai-engineer", root)
    assert project is not None
    script = demo_internship.internship()
    script.colleagues[0].persona = PERSONA
    work.write_internship(root, project.blueprint_id, script)
    replies = Replies()
    settings = wsapi.get_settings()
    monkeypatch.setattr(
        wsapi,
        "gateway",
        lambda: LLMGateway(
            settings=settings, completion_fn=replies, tracer=NoopTracer(),
            budgets=BudgetRegistry(Decimal("5")), recorder=lambda _: None,
        ),
    )  # fmt: skip
    monkeypatch.setattr(api, "chat_limit", Limiter(40, 3600))
    monkeypatch.setattr(api, "chat_day_limit", Limiter(500, 86400))
    monkeypatch.setattr(api, "verdict_limit", Limiter(5, 3600))
    monkeypatch.setattr(api, "verdict_day_limit", Limiter(100, 86400))
    return runner, replies


CHAT = {"colleague": "maya", "day": 2, "message": "Where should I start?", "history": []}


@pytest.mark.db
def test_the_script_has_names_and_events_but_no_personas(
    team: tuple[FakeRunner, Replies],
) -> None:
    body = client.get("/roles/genai-engineer/internship").json()
    assert {c["key"] for c in body["colleagues"]} == {"maya", "dev", "sam"}
    assert set(body["colleagues"][0]) == {"key", "name", "role"}
    assert PERSONA not in str(body)
    assert client.get("/roles/unknown/internship").status_code == 404


@pytest.mark.db
def test_a_colleague_replies_in_character_and_never_sees_the_key(
    team: tuple[FakeRunner, Replies],
) -> None:
    _, replies = team
    history = [{"who": "you", "text": "Hi"}, {"who": "them", "text": "Welcome!"}]
    res = client.post("/roles/genai-engineer/internship/chat", json={**CHAT, "history": history})
    assert res.status_code == 200 and "total" in res.json()["reply"]
    prompt = str(replies.messages[0])
    assert PERSONA in prompt and "Maya Okafor" in prompt
    assert "Welcome!" in prompt and SECRET not in prompt
    assert "Day 2" in prompt and "Friday retro" not in prompt  # nothing from the future


@pytest.mark.db
def test_chat_refuses_unknown_colleagues_bad_days_and_too_many_messages(
    team: tuple[FakeRunner, Replies], monkeypatch: pytest.MonkeyPatch
) -> None:
    url = "/roles/genai-engineer/internship/chat"
    assert client.post(url, json={**CHAT, "colleague": "nobody"}).status_code == 422
    assert client.post(url, json={**CHAT, "day": 9}).status_code == 422
    monkeypatch.setattr(api, "chat_limit", Limiter(1, 3600))
    assert client.post(url, json=CHAT).status_code == 200
    assert client.post(url, json=CHAT).status_code == 429


@pytest.mark.db
def test_the_review_runs_the_tests_then_returns_a_validated_verdict(
    team: tuple[FakeRunner, Replies],
) -> None:
    runner, replies = team
    res = client.post(
        "/roles/genai-engineer/internship/verdict",
        json={
            "files": {"src/calc.py": "def total(xs):\n    return sum(xs)\n"},
            "chat": ["Hi Maya"],
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["verdict"]["skills"][0]["skill_id"] == "python"
    assert body["tests"]["passed"] is False and len(runner.jobs) == 1
    prompt = str(replies.messages[0])
    assert "Hi Maya" in prompt and "return sum(xs)" in prompt and SECRET not in prompt


@pytest.mark.db
def test_without_a_key_the_team_is_unavailable(
    team: tuple[FakeRunner, Replies], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(
        _env_file=None, gemini_api_key=None, artifacts_dir=wsapi.get_settings().artifacts_dir
    )
    monkeypatch.setattr(wsapi, "get_settings", lambda: settings)
    res = client.post("/roles/genai-engineer/internship/chat", json=CHAT)
    assert res.status_code == 503
