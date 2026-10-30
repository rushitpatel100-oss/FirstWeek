"""FirstWeek HTTP API. Run with: uvicorn firstweek_api.main:app --reload"""

import asyncio
import inspect
import uuid
from typing import Any

import redis.asyncio as aioredis
from fastapi import FastAPI, HTTPException, Response
from sqlalchemy import text
from temporalio.client import Client

from firstweek_core import __version__
from firstweek_core.config import get_settings
from firstweek_core.db.session import get_engine

app = FastAPI(title="FirstWeek API", version=__version__)

CHECK_TIMEOUT_S = 3.0


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness: the process is up. Does not touch dependencies."""
    return {"status": "ok", "version": __version__}


def _check_database() -> None:
    with get_engine().connect() as conn:
        conn.execute(text("SELECT 1"))


async def _check_redis() -> None:
    client = aioredis.from_url(get_settings().redis_url)
    try:
        await client.ping()
    finally:
        await client.aclose()


async def _check_temporal() -> None:
    settings = get_settings()
    await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)


async def _run_check(name: str, check: Any) -> tuple[str, str]:
    try:
        if inspect.iscoroutinefunction(check):
            await asyncio.wait_for(check(), CHECK_TIMEOUT_S)
        else:
            await asyncio.wait_for(asyncio.to_thread(check), CHECK_TIMEOUT_S)
        return name, "ok"
    except Exception as exc:
        return name, f"error: {type(exc).__name__}"


@app.get("/ready")
async def ready(response: Response) -> dict[str, Any]:
    """Readiness: every dependency answers. Returns 503 if any does not."""
    results = dict(
        await asyncio.gather(
            _run_check("database", _check_database),
            _run_check("redis", _check_redis),
            _run_check("temporal", _check_temporal),
        )
    )
    all_ok = all(v == "ok" for v in results.values())
    if not all_ok:
        response.status_code = 503
    return {"status": "ok" if all_ok else "degraded", "checks": results}


@app.post("/system/smoke")
async def smoke(name: str = "there") -> dict[str, Any]:
    """Runs the smoke workflow end to end: API -> Temporal -> worker -> database."""
    settings = get_settings()
    try:
        client = await Client.connect(
            settings.temporal_address, namespace=settings.temporal_namespace
        )
        result: dict[str, Any] = await client.execute_workflow(
            "SmokeWorkflow",
            name,
            id=f"smoke-{uuid.uuid4()}",
            task_queue=settings.temporal_task_queue,
            result_type=dict,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Smoke workflow failed: {exc}") from exc
    return result
