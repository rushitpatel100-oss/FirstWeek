"""Database tests. They run when DATABASE_URL points at a migrated Postgres with pgvector."""

from decimal import Decimal

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import OperationalError

from firstweek_core.db import Base
from firstweek_core.db.models import LLMCall
from firstweek_core.db.session import get_engine, session_scope
from firstweek_core.llm.gateway import CallRecord
from firstweek_core.llm.recorder import record_to_db

pytestmark = pytest.mark.db


@pytest.fixture(scope="module", autouse=True)
def _require_database() -> None:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError:
        pytest.skip("No database available (set DATABASE_URL and run migrations)")


def test_every_model_table_exists() -> None:
    existing = set(inspect(get_engine()).get_table_names())
    missing = set(Base.metadata.tables) - existing
    assert not missing, f"run 'make migrate' first; missing tables: {missing}"


def test_vector_extension_is_installed() -> None:
    with get_engine().connect() as conn:
        version = conn.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        ).scalar()
    assert version is not None


def test_recorder_writes_llm_calls() -> None:
    record = CallRecord(
        purpose="test-recorder",
        tier="small",
        model="anthropic/claude-haiku-5-5",
        budget_scope="pytest",
        prompt_version="v0",
        tokens_in=10,
        tokens_out=5,
        cost_usd=Decimal("0.000004"),
        latency_ms=12,
        success=True,
        error=None,
        trace_id=None,
    )
    record_to_db(record)
    with session_scope() as session:
        row = session.scalars(
            select(LLMCall)
            .where(LLMCall.purpose == "test-recorder")
            .order_by(LLMCall.created_at.desc())
        ).first()
        assert row is not None
        assert row.cost_usd == Decimal("0.000004")
        session.delete(row)
