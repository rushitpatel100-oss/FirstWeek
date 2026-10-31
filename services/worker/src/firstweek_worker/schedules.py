"""The daily research schedule, kept in step with settings every time the worker starts.

Development Temporal runs in memory, so schedules vanish when its container restarts. The
worker therefore (re)creates the schedule on start-up. A laptop is often off at the
scheduled time, so if the last collection is over STALE_AFTER old, the worker also starts a
run straight away. Over weeks this builds the rolling window the statistics use.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleAlreadyRunningError,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
    ScheduleUpdate,
    ScheduleUpdateInput,
)
from temporalio.service import RPCError, RPCStatusCode

from firstweek_core.config import Settings
from firstweek_core.db.models import JobPosting
from firstweek_core.db.session import session_scope
from firstweek_research.roles import load_roles
from firstweek_worker.research_workflow import DailyResearchInput, DailyResearchWorkflow

SCHEDULE_ID = "daily-research"
STALE_AFTER = timedelta(hours=20)

log = logging.getLogger("firstweek.worker")


def golden_roles() -> list[str]:
    return sorted(slug for slug, r in load_roles().items() if r.trust_level == "golden")


def last_collected_at() -> datetime | None:
    with session_scope() as session:
        return session.scalar(select(func.max(JobPosting.last_seen_at)))


def daily_input(settings: Settings) -> DailyResearchInput:
    return DailyResearchInput(
        role_slugs=golden_roles(),
        country="GB",
        budget_usd_per_role=settings.research_budget_usd_per_role,
    )


def build_schedule(settings: Settings) -> Schedule:
    return Schedule(
        action=ScheduleActionStartWorkflow(
            DailyResearchWorkflow.run,
            daily_input(settings),
            id="daily-research-run",
            task_queue=settings.temporal_task_queue,
            execution_timeout=timedelta(hours=6),
        ),
        spec=ScheduleSpec(
            cron_expressions=[settings.research_daily_cron],
            time_zone_name=settings.research_daily_timezone,
        ),
        # Never two runs at once: a slow run simply makes the next one wait its turn.
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )


async def ensure_daily_research(
    client: Client, settings: Settings, *, now: datetime | None = None
) -> str:
    """Creates, updates or removes the schedule to match settings. Returns what it did."""
    handle = client.get_schedule_handle(SCHEDULE_ID)
    if not settings.research_daily_enabled:
        try:
            await handle.delete()
        except RPCError as exc:
            if exc.status != RPCStatusCode.NOT_FOUND:
                raise
        return "Daily research is off (RESEARCH_DAILY_ENABLED=false)."

    schedule = build_schedule(settings)
    last = await asyncio.to_thread(last_collected_at)
    stale = last is None or (now or datetime.now(UTC)) - last > STALE_AFTER
    try:
        await client.create_schedule(SCHEDULE_ID, schedule, trigger_immediately=stale)
    except ScheduleAlreadyRunningError:

        def replace(_: ScheduleUpdateInput) -> ScheduleUpdate:
            return ScheduleUpdate(schedule=schedule)

        await handle.update(replace)
        if stale:
            await handle.trigger(overlap=ScheduleOverlapPolicy.SKIP)
    when = f"'{settings.research_daily_cron}' ({settings.research_daily_timezone})"
    first = (
        "starting a run now, as the last collection is over 20 hours old"
        if stale
        else (f"last collection {last:%Y-%m-%d %H:%M} UTC" if last else "no collection yet")
    )
    return f"Daily research scheduled at {when} for {', '.join(golden_roles())}; {first}."
