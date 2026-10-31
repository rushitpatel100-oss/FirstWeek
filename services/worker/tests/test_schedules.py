"""The daily schedule against a real local Temporal dev server (schedules need one)."""

from datetime import UTC, datetime, timedelta

import pytest
from temporalio.client import ScheduleActionStartWorkflow
from temporalio.service import RPCError
from temporalio.testing import WorkflowEnvironment

from firstweek_core.config import Settings
from firstweek_worker import schedules
from firstweek_worker.research_workflow import DailyResearchInput

NOW = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, temporal_task_queue="schedule-test", **overrides)  # type: ignore[arg-type]


async def _dev_server() -> WorkflowEnvironment:
    try:
        return await WorkflowEnvironment.start_local()
    except Exception as exc:  # the dev server binary is downloaded on first use
        pytest.skip(f"Temporal dev server unavailable: {exc}")


async def test_schedule_is_created_updated_and_removed(monkeypatch: pytest.MonkeyPatch) -> None:
    last_seen: list[datetime | None] = [None]
    monkeypatch.setattr(schedules, "last_collected_at", lambda: last_seen[0])
    triggered: list[bool] = []
    async with await _dev_server() as env:
        client = env.client
        real_create = client.create_schedule

        async def spy_create(*args: object, **kwargs: object) -> object:
            triggered.append(bool(kwargs.get("trigger_immediately")))
            return await real_create(*args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(client, "create_schedule", spy_create)

        # 1. First start, nothing collected yet: create and run straight away.
        message = await schedules.ensure_daily_research(client, _settings(), now=NOW)
        assert triggered == [True]
        assert "starting a run now" in message
        described = await client.get_schedule_handle(schedules.SCHEDULE_ID).describe()
        action = described.schedule.action
        assert isinstance(action, ScheduleActionStartWorkflow)
        assert action.workflow == "DailyResearchWorkflow"
        assert described.schedule.spec.time_zone_name == "Europe/London"

        # 2. Restart an hour after a collection: update the schedule, no extra run.
        last_seen[0] = NOW - timedelta(hours=1)
        message = await schedules.ensure_daily_research(
            client, _settings(research_daily_cron="5 6 * * *"), now=NOW
        )
        assert "last collection 2026-10-31 11:00" in message
        described = await client.get_schedule_handle(schedules.SCHEDULE_ID).describe()
        calendar = described.schedule.spec.calendars[0]  # the server stores cron as a calendar
        assert (calendar.hour[0].start, calendar.minute[0].start) == (6, 5)

        # 3. Switched off: the schedule is removed, and removing twice is fine.
        off = _settings(research_daily_enabled=False)
        assert "off" in await schedules.ensure_daily_research(client, off, now=NOW)
        await schedules.ensure_daily_research(client, off, now=NOW)
        with pytest.raises(RPCError):
            await client.get_schedule_handle(schedules.SCHEDULE_ID).describe()


def test_daily_input_covers_every_golden_role() -> None:
    inp = schedules.daily_input(_settings(research_budget_usd_per_role=0.75))
    assert inp == DailyResearchInput(
        ["agentic-ai-engineer", "ai-software-engineer", "genai-engineer"],
        country="GB",
        budget_usd_per_role=0.75,
    )
