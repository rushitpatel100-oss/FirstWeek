"""Temporal worker entry point: python -m firstweek_worker.main"""

import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from firstweek_core.config import get_settings
from firstweek_worker.smoke import SmokeWorkflow, check_database

log = logging.getLogger("firstweek.worker")

WORKFLOWS = [SmokeWorkflow]
ACTIVITIES = [check_database]


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
    log.info("Worker listening on task queue '%s'", settings.temporal_task_queue)
    await worker.run()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    asyncio.run(run())


if __name__ == "__main__":
    main()
