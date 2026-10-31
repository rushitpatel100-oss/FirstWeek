"""Runs the smoke workflow on Temporal's in-process test server, with the activity mocked."""

import uuid

import pytest
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from firstweek_worker.smoke import SmokeResult, SmokeWorkflow


@activity.defn(name="check_database")
async def fake_check_database() -> bool:
    return True


async def test_smoke_workflow_greets_and_reports_database() -> None:
    try:
        env = await WorkflowEnvironment.start_time_skipping()
    except Exception as exc:  # the test server binary is downloaded on first use
        pytest.skip(f"Temporal test server unavailable: {exc}")

    async with (
        env,
        Worker(
            env.client,
            task_queue="test-queue",
            workflows=[SmokeWorkflow],
            activities=[fake_check_database],
        ),
    ):
        result = await env.client.execute_workflow(
            SmokeWorkflow.run,
            "Rushit",
            id=f"smoke-{uuid.uuid4()}",
            task_queue="test-queue",
            result_type=SmokeResult,
        )
    assert result.database_ok is True
    assert "Rushit" in result.greeting
