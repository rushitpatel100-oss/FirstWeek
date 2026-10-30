"""Persist every model call to the llm_calls table, for cost and quality analysis."""

from firstweek_core.db.models import LLMCall
from firstweek_core.db.session import session_scope
from firstweek_core.llm.gateway import CallRecord


def record_to_db(record: CallRecord) -> None:
    with session_scope() as session:
        session.add(
            LLMCall(
                purpose=record.purpose,
                tier=record.tier,
                model=record.model,
                budget_scope=record.budget_scope,
                prompt_version=record.prompt_version,
                tokens_in=record.tokens_in,
                tokens_out=record.tokens_out,
                cost_usd=record.cost_usd,
                latency_ms=record.latency_ms,
                success=record.success,
                error=record.error,
                trace_id=record.trace_id,
            )
        )
