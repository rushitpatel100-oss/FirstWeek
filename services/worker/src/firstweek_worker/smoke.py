"""A smoke workflow that proves the API -> Temporal -> worker -> database path works."""

import asyncio
from dataclasses import dataclass
from datetime import timedelta

from temporalio import activity, workflow

with workflow.unsafe.imports_passed_through():
    from sqlalchemy import text

    from firstweek_core.db.session import get_engine


@dataclass
class SmokeResult:
    greeting: str
    database_ok: bool


def _database_ok() -> bool:
    try:
        with get_engine().connect() as conn:
            return conn.execute(text("SELECT 1")).scalar() == 1
    except Exception:
        return False


@activity.defn
async def check_database() -> bool:
    return await asyncio.to_thread(_database_ok)


@workflow.defn(name="SmokeWorkflow")
class SmokeWorkflow:
    @workflow.run
    async def run(self, name: str) -> SmokeResult:
        database_ok = await workflow.execute_activity(
            check_database, start_to_close_timeout=timedelta(seconds=10)
        )
        return SmokeResult(greeting=f"Hello {name}, FirstWeek is running.", database_ok=database_ok)
