"""The skill-gap endpoint: published reports only, private text, and spending fenced."""

from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from test_reports import _clean, add_report

from firstweek_api import skill_gap as sg
from firstweek_api.main import app
from firstweek_core.config import Settings
from firstweek_core.contracts import GapDraftItem, GapReply
from firstweek_core.llm import BudgetRegistry, LLMGateway
from firstweek_core.llm.tracing import NoopTracer

__all__ = ["_clean"]  # registers the fixture here

client = TestClient(app)
BACKGROUND = "I was a mechanical engineer. I write Python scripts to analyse test data."


async def _completion(**kwargs: Any) -> SimpleNamespace:
    reply = GapReply(
        items=[
            GapDraftItem(
                skill_id="python",
                status="have",
                background_quote="write Python scripts",
                reason="You state it.",
            )
        ]
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=reply.model_dump_json()))],
        usage=SimpleNamespace(prompt_tokens=500, completion_tokens=100),
    )


@pytest.fixture(autouse=True)
def _wired(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sg,
        "gateway",
        lambda: LLMGateway(
            settings=Settings(_env_file=None),
            completion_fn=_completion,
            tracer=NoopTracer(),
            budgets=BudgetRegistry(Decimal("5")),
        ),
    )
    monkeypatch.setattr(
        sg, "get_settings", lambda: Settings(_env_file=None, anthropic_api_key=SecretStr("k"))
    )
    monkeypatch.setattr(sg, "client_limit", sg.Limiter(*sg.PER_CLIENT))
    monkeypatch.setattr(sg, "day_limit", sg.Limiter(*sg.PER_DAY))


@pytest.mark.db
def test_a_background_is_compared_with_the_published_reports_skills() -> None:
    add_report("genai-engineer", "GenAI Engineer", "published", "New")
    response = client.post("/roles/genai-engineer/skill-gap", json={"background": BACKGROUND})
    assert response.status_code == 200
    body = response.json()
    assert body["lines"][0]["label"] == "Python" and body["lines"][0]["status"] == "have"
    assert 'you wrote: "write Python scripts"' in body["lines"][0]["reason"]
    assert body["coverage"] == 1.0


@pytest.mark.db
def test_nothing_is_compared_for_an_unpublished_role_or_a_bad_background() -> None:
    add_report("genai-engineer", "GenAI Engineer", "draft", "Draft")
    assert (
        client.post("/roles/genai-engineer/skill-gap", json={"background": BACKGROUND}).status_code
        == 404
    )
    add_report("agentic-ai-engineer", "Agentic AI Engineer", "published", "Agentic")
    path = "/roles/agentic-ai-engineer/skill-gap"
    assert client.post(path, json={"background": ""}).status_code == 422
    assert client.post(path, json={"background": "x" * 2001}).status_code == 422
    assert client.post(path, json={"background": "   "}).status_code == 422  # blank after trim


@pytest.mark.db
def test_the_service_says_so_when_it_has_no_model_key(monkeypatch: pytest.MonkeyPatch) -> None:
    add_report("genai-engineer", "GenAI Engineer", "published", "New")
    monkeypatch.setattr(
        sg, "get_settings", lambda: Settings(_env_file=None, anthropic_api_key=None)
    )
    response = client.post("/roles/genai-engineer/skill-gap", json={"background": BACKGROUND})
    assert response.status_code == 503


@pytest.mark.db
def test_a_client_is_limited_to_five_a_hour() -> None:
    add_report("genai-engineer", "GenAI Engineer", "published", "New")
    statuses = [
        client.post("/roles/genai-engineer/skill-gap", json={"background": BACKGROUND}).status_code
        for _ in range(6)
    ]
    assert statuses == [200] * 5 + [429]


def test_the_limiter_forgets_old_calls() -> None:
    now = [0.0]
    limiter = sg.Limiter(2, 10, clock=lambda: now[0])
    assert [limiter.allow("a"), limiter.allow("a"), limiter.allow("a")] == [True, True, False]
    assert limiter.allow("b")  # another client is unaffected
    now[0] = 11.0
    assert limiter.allow("a")
