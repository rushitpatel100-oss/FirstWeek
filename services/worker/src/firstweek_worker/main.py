"""Temporal worker entry point: python -m firstweek_worker.main"""

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from temporalio.client import Client
from temporalio.worker import Worker

from firstweek_core.config import get_settings
from firstweek_worker.research_activities import (
    analyse_role,
    check_code_version,
    collect_role,
    index_evidence,
)
from firstweek_worker.research_workflow import DailyResearchWorkflow
from firstweek_worker.schedules import ensure_daily_research
from firstweek_worker.smoke import SmokeWorkflow, check_database

log = logging.getLogger("firstweek.worker")

WORKFLOWS: list[type] = [SmokeWorkflow, DailyResearchWorkflow]
ACTIVITIES: list[Callable[..., Any]] = [
    check_database,
    check_code_version,
    collect_role,
    analyse_role,
    index_evidence,
]


async def connect_with_retry(address: str, namespace: str, attempts: int = 30) -> Client:
    """Temporal can take a few seconds to start in Docker Compose."""
    for attempt in range(1, attempts + 1):
        try:
            return await Client.connect(address, namespace=namespace)
        except Exception as exc:
            if attempt == attempts:
                raise
            log.info("Temporal not ready (%s); retry %d/%d", exc, attempt, attempts)
            await asyncio.sleep(2)
    raise RuntimeError("unreachable")


async def run() -> None:
    settings = get_settings()
    client = await connect_with_retry(settings.temporal_address, settings.temporal_namespace)
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=WORKFLOWS,
        activities=ACTIVITIES,
    )
    try:
        log.info(await ensure_daily_research(client, settings))
    except Exception:  # the worker must still start, for the API and other workflows
        log.exception("Could not set up the daily research schedule")
    log.info("Worker listening on task queue '%s'", settings.temporal_task_queue)
    await worker.run()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    for noisy in ("httpx", "LiteLLM"):  # one line per HTTP request drowns the progress lines
        logging.getLogger(noisy).setLevel(logging.WARNING)
    asyncio.run(run())


if __name__ == "__main__":
    main()
