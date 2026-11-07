"""The workspace endpoints: public project only, tests through the sandbox, reviews fenced."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from test_reports import _clean

from firstweek_api import workspace as wsapi
from firstweek_api.main import app
from firstweek_api.skill_gap import Limiter
from firstweek_core.config import Settings
from firstweek_core.db.models import ArchetypeVersion, Blueprint, RoleArchetype
from firstweek_core.db.session import session_scope
from firstweek_core.llm import BudgetRegistry, LLMGateway
from firstweek_core.llm.tracing import NoopTracer
from firstweek_core.sandbox import JobResult, SandboxJob

__all__ = ["_clean"]

client = TestClient(app)
SECRET = "PLANTED-OFF-BY-ONE-IN-TOTAL"
TICKET = {
    "key": "GENAI-101",
    "title": "Fix the total",
    "description": "The total is wrong for lists.",
    "acceptance_criteria": ["sums every item"],
    "task_type": "code",
    "due_day": 1,
    "skills": ["python"],
}


class FakeRunner:
    def __init__(self, exit_code: int = 1) -> None:
        self.jobs: list[SandboxJob] = []
        self.exit_code = exit_code

    async def run(self, job: SandboxJob) -> JobResult:
        self.jobs.append(job)
        return JobResult(exit_code=self.exit_code, stdout="1 failed", stderr="", duration_s=0.1)


class Prompts:
    def __init__(self) -> None:
        self.messages: list[Any] = []

    async def __call__(self, **kwargs: Any) -> SimpleNamespace:
        self.messages.append(kwargs["messages"])
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="Tests fail. Check src/calc.py total."),
                    finish_reason="stop",
                )
            ],
            usage=SimpleNamespace(prompt_tokens=300, completion_tokens=60),
        )


@pytest.fixture
def world(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, _clean: None
) -> tuple[FakeRunner, Prompts]:
    with session_scope() as session:
        role = RoleArchetype(
            slug="genai-engineer", name="GenAI Engineer", definition="d", trust_level="golden"
        )
        session.add(role)
        session.flush()
        version = ArchetypeVersion(
            archetype_id=role.id, version=1, country="GB", date_from=date(2026, 5, 1),
            date_to=date(2026, 10, 1), sample_size=15, status="published",
        )  # fmt: skip
        session.add(version)
        session.flush()
        row = Blueprint(
            archetype_version_id=version.id, scenario="A claims team.",
            blueprint={
                "scenario": "A claims team.",
                "company_context": "Northwind, an insurer.",
                "tickets": [TICKET],
                "rubric": [
                    {"skill_id": "python", "weight": 1.0, "anchors": {"1": "bad", "5": "good"},
                     "checks": ["tests pass"]}
                ],
            },
            answer_key={"planted_issues": [SECRET]}, validated=True, status="approved",
        )  # fmt: skip
        session.add(row)
        session.flush()
        folder = tmp_path / str(row.id)
    for name, files in {
        "starter": {"src/calc.py": "def total(xs):\n    return 0\n", "tests/test_calc.py": "T\n"},
        "reference": {"src/calc.py": "REFERENCE-SOLUTION"},
        "key": {"key/metrics.py": "HIDDEN"},
    }.items():
        for path, text in files.items():
            (folder / name / path).parent.mkdir(parents=True, exist_ok=True)
            (folder / name / path).write_text(text)
    # The gateway exports provider keys to the environment; let pytest undo that afterwards.
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    runner, prompts = FakeRunner(), Prompts()
    settings = Settings(_env_file=None, gemini_api_key=SecretStr("k"), artifacts_dir=str(tmp_path))
    monkeypatch.setattr(wsapi, "get_settings", lambda: settings)
    monkeypatch.setattr(wsapi, "runner", lambda: runner)
    monkeypatch.setattr(
        wsapi,
        "gateway",
        lambda: LLMGateway(
            settings=settings, completion_fn=prompts, tracer=NoopTracer(),
            budgets=BudgetRegistry(Decimal("5")), recorder=lambda _: None,
        ),
    )  # fmt: skip
    monkeypatch.setattr(wsapi, "tests_limit", Limiter(30, 3600))
    monkeypatch.setattr(wsapi, "review_limit", Limiter(10, 3600))
    monkeypatch.setattr(wsapi, "review_day_limit", Limiter(200, 86400))
    return runner, prompts


@pytest.mark.db
def test_the_project_shows_starter_files_and_never_the_key_or_the_solution(
    world: tuple[FakeRunner, Prompts],
) -> None:
    body = client.get("/roles/genai-engineer/project").json()
    assert set(body["files"]) == {"src/calc.py", "tests/test_calc.py"}
    assert body["blueprint"]["tickets"][0]["key"] == "GENAI-101"
    assert SECRET not in str(body) and "REFERENCE" not in str(body) and "HIDDEN" not in str(body)
    assert client.get("/roles/unknown/project").status_code == 404


@pytest.mark.db
def test_running_tests_overlays_the_edits_but_given_tests_and_the_hidden_side_are_protected(
    world: tuple[FakeRunner, Prompts],
) -> None:
    runner, _ = world
    edits = {"src/calc.py": "def total(xs):\n    return sum(xs)\n", "tests/test_calc.py": "CHEAT\n"}
    body = client.post("/roles/genai-engineer/project/tests", json={"files": edits}).json()
    assert body == {"exit_code": 1, "output": "1 failed", "timed_out": False, "passed": False}
    sent = runner.jobs[0].files
    assert "sum(xs)" in sent["src/calc.py"] and sent["tests/test_calc.py"] == "T\n"
    hidden = client.post(
        "/roles/genai-engineer/project/tests", json={"files": {"key/metrics.py": "x"}}
    )
    assert hidden.status_code == 422 and len(runner.jobs) == 1
    odd = client.post("/roles/genai-engineer/project/tests", json={"files": {"../x": "x"}})
    assert odd.status_code == 422


@pytest.mark.db
def test_a_review_runs_the_tests_itself_and_the_reviewer_never_sees_the_key(
    world: tuple[FakeRunner, Prompts],
) -> None:
    runner, prompts = world
    response = client.post(
        "/roles/genai-engineer/project/review",
        json={"ticket": "GENAI-101", "files": {"src/calc.py": "def total(xs):\n    return 1\n"}},
    )
    assert response.status_code == 200 and "Check src/calc.py" in response.json()["review"]
    assert response.json()["tests"]["passed"] is False and len(runner.jobs) == 1
    prompt = str(prompts.messages)
    assert "1 failed" in prompt and "return 1" in prompt and "sums every item" in prompt
    assert SECRET not in prompt and "REFERENCE" not in prompt and "HIDDEN" not in prompt
    unknown = client.post("/roles/genai-engineer/project/review", json={"ticket": "GENAI-999"})
    assert unknown.status_code == 422


@pytest.mark.db
def test_reviews_need_a_key_and_are_rate_limited(
    world: tuple[FakeRunner, Prompts], monkeypatch: pytest.MonkeyPatch
) -> None:
    body = {"ticket": "GENAI-101", "files": {}}
    statuses = [
        client.post("/roles/genai-engineer/project/review", json=body).status_code
        for _ in range(11)
    ]
    assert statuses == [200] * 10 + [429]
    monkeypatch.setattr(wsapi, "review_limit", Limiter(10, 3600))
    no_key = Settings(
        _env_file=None, gemini_api_key=None, artifacts_dir=wsapi.get_settings().artifacts_dir
    )
    monkeypatch.setattr(wsapi, "get_settings", lambda: no_key)
    assert client.post("/roles/genai-engineer/project/review", json=body).status_code == 503


@pytest.mark.db
def test_a_dead_code_runner_is_a_503_not_a_failing_test(
    world: tuple[FakeRunner, Prompts],
) -> None:
    runner, _ = world
    runner.exit_code = 125  # what `docker run` returns when the daemon or image is missing
    path = "/roles/genai-engineer/project"
    assert client.post(f"{path}/tests", json={"files": {}}).status_code == 503
    review = client.post(f"{path}/review", json={"ticket": "GENAI-101", "files": {}})
    assert review.status_code == 503
