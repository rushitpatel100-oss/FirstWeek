"""The daily research workflow and its activities, with research steps faked: no network,
no model calls, no database."""

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment, WorkflowEnvironment
from temporalio.worker import Worker

from firstweek_core.config import Settings
from firstweek_worker import research_activities
from firstweek_worker.research_activities import AnalyseOutcome, CollectOutcome, RoleRunInput
from firstweek_worker.research_workflow import (
    DailyResearchInput,
    DailyResearchReport,
    DailyResearchWorkflow,
)

ROLES = ["agentic-ai-engineer", "ai-software-engineer", "genai-engineer"]


@activity.defn(name="collect_role")
async def fake_collect(inp: RoleRunInput) -> CollectOutcome:
    if inp.role_slug == "ai-software-engineer":
        raise ApplicationError("every job board timed out", non_retryable=True)
    return CollectOutcome(inp.role_slug, new=3)


@activity.defn(name="check_code_version")
async def fake_check_code(expected: str) -> str:
    if expected != "abc123":
        raise ApplicationError(
            f"worker has abc123, you have {expected}",
            type=research_activities.CODE_MISMATCH,
            non_retryable=True,
        )
    return expected


@activity.defn(name="analyse_role")
async def fake_analyse(inp: RoleRunInput) -> AnalyseOutcome:
    return AnalyseOutcome(inp.role_slug, classified=3, cost_usd=0.05, sample_size=12, version=4)


async def _environment() -> WorkflowEnvironment:
    try:
        return await WorkflowEnvironment.start_time_skipping()
    except Exception as exc:  # the test server binary is downloaded on first use
        pytest.skip(f"Temporal test server unavailable: {exc}")


async def test_one_failing_role_does_not_stop_the_others() -> None:
    env = await _environment()
    async with (
        env,
        Worker(
            env.client,
            task_queue="research-test",
            workflows=[DailyResearchWorkflow],
            activities=[fake_collect, fake_analyse],
        ),
    ):
        report = await env.client.execute_workflow(
            DailyResearchWorkflow.run,
            DailyResearchInput(ROLES, budget_usd_per_role=0.5),
            id=f"research-{uuid.uuid4()}",
            task_queue="research-test",
        )
    assert isinstance(report, DailyResearchReport)
    by_role = {r.role_slug: r for r in report.roles}
    assert [r.role_slug for r in report.roles] == ROLES  # run in the given order
    failed = by_role["ai-software-engineer"]
    assert failed.analysed is None and failed.error and "timed out" in failed.error
    for slug in ("agentic-ai-engineer", "genai-engineer"):
        assert by_role[slug].analysed is not None and by_role[slug].error is None
    assert report.cost_usd == pytest.approx(0.10)


@pytest.mark.parametrize(("expected", "runs"), [("abc123", True), ("old999", False)])
async def test_a_run_started_by_hand_stops_if_the_worker_code_differs(
    expected: str, runs: bool
) -> None:
    from temporalio.client import WorkflowFailureError

    from firstweek_worker.run_research_now import _code_mismatch

    env = await _environment()
    async with (
        env,
        Worker(
            env.client,
            task_queue="research-test",
            workflows=[DailyResearchWorkflow],
            activities=[fake_check_code, fake_collect, fake_analyse],
        ),
    ):
        start = env.client.execute_workflow(
            DailyResearchWorkflow.run,
            DailyResearchInput(["genai-engineer"], expected_code=expected),
            id=f"research-{uuid.uuid4()}",
            task_queue="research-test",
        )
        if runs:
            report = await start
            assert report.roles[0].analysed is not None
        else:
            with pytest.raises(WorkflowFailureError) as failure:
                await start
            assert _code_mismatch(failure.value) == "worker has abc123, you have old999"


def test_code_fingerprint_changes_with_a_definition(monkeypatch: pytest.MonkeyPatch) -> None:
    from firstweek_research.research import code_fingerprint
    from firstweek_research.roles import RoleDefinition

    before = code_fingerprint()
    assert before == code_fingerprint() and len(before) == 12  # stable
    monkeypatch.setattr(RoleDefinition, "definition_hash", property(lambda _: "edited00edited00"))
    assert code_fingerprint() != before


async def test_analysis_is_skipped_without_an_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        research_activities, "get_settings", lambda: Settings(_env_file=None, anthropic_api_key="")
    )
    outcome = await ActivityEnvironment().run(
        research_activities.analyse_role, RoleRunInput("genai-engineer")
    )
    assert outcome.skipped == "ANTHROPIC_API_KEY is not set" and outcome.cost_usd == 0


async def test_collect_activity_reports_counts_and_heartbeats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run_collect(role_slug: str, settings: Settings, **kwargs: Any) -> Any:
        kwargs["progress"]("Fetching 80 company job boards...")
        stats = {
            "greenhouse": SimpleNamespace(new=2, updated=1),
            "ashby": SimpleNamespace(new=1, updated=0),
        }
        return SimpleNamespace(
            providers=stats, errors={"board:Acme": "404"}, skipped={"web": "no key"}
        )

    monkeypatch.setattr(research_activities, "run_collect", fake_run_collect)
    beats: list[Any] = []
    env = ActivityEnvironment()
    env.on_heartbeat = lambda *details: beats.append(details)
    outcome = await env.run(research_activities.collect_role, RoleRunInput("genai-engineer"))
    assert (outcome.new, outcome.updated) == (3, 1)
    assert outcome.errors == ["board:Acme: 404"] and outcome.skipped == ["web: no key"]
    assert beats == [("Fetching 80 company job boards...",)]
