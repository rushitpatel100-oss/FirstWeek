"""Gateway tests. None of them call a real model, so they cost nothing and need no keys."""

from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from firstweek_core.config import Settings
from firstweek_core.llm import (
    BudgetExceededError,
    BudgetRegistry,
    CallRecord,
    LLMGateway,
    StructuredOutputError,
    Tier,
)


def _response(content: str, tokens_in: int = 1000, tokens_out: int = 200) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=tokens_in, completion_tokens=tokens_out),
    )


class FakeLLM:
    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return _response(self.replies.pop(0))


class FakeHandle:
    trace_id = "trace-1"

    def __init__(self) -> None:
        self.finished: dict[str, Any] = {}

    def finish(self, **kwargs: Any) -> None:
        self.finished = kwargs


class FakeTracer:
    def __init__(self) -> None:
        self.handles: list[FakeHandle] = []

    @contextmanager
    def generation(self, **_: Any) -> Iterator[FakeHandle]:
        handle = FakeHandle()
        self.handles.append(handle)
        yield handle

    def flush(self) -> None:
        return None


def _gateway(llm: FakeLLM, limit: str = "1.00") -> tuple[LLMGateway, list[CallRecord], FakeTracer]:
    records: list[CallRecord] = []
    tracer = FakeTracer()
    gateway = LLMGateway(
        settings=Settings(_env_file=None),
        completion_fn=llm,
        tracer=tracer,
        recorder=records.append,
        budgets=BudgetRegistry(Decimal(limit)),
    )
    return gateway, records, tracer


class Verdict(BaseModel):
    supported: bool
    reason: str


async def test_complete_routes_by_tier_and_records_cost() -> None:
    llm = FakeLLM(["hello"])
    gateway, records, tracer = _gateway(llm)

    result = await gateway.complete(
        purpose="smoke", messages=[{"role": "user", "content": "hi"}], tier="small"
    )

    assert llm.calls[0]["model"] == "anthropic/claude-haiku-5-5"
    assert result.content == "hello"
    # Haiku 5.5: 1000 * 0.10/M + 200 * 0.50/M
    assert result.cost_usd == Decimal("0.0002")
    assert result.trace_id == "trace-1"
    assert records[0].success and records[0].cost_usd == result.cost_usd
    assert tracer.handles[0].finished["tokens_in"] == 1000


async def test_budget_blocks_before_spending() -> None:
    llm = FakeLLM(["never sent"])
    gateway, records, _ = _gateway(llm, limit="0.01")

    with pytest.raises(BudgetExceededError):
        await gateway.complete(
            purpose="review",
            messages=[{"role": "user", "content": "x" * 30_000}],
            tier="frontier",
            max_tokens=4000,
        )
    assert llm.calls == []
    assert records == []


async def test_downgrade_when_allowed() -> None:
    llm = FakeLLM(["cheap answer"])
    gateway, _, _ = _gateway(llm, limit="0.05")

    result = await gateway.complete(
        purpose="chat",
        messages=[{"role": "user", "content": "x" * 3_000}],
        tier="frontier",
        max_tokens=4000,
        allow_downgrade=True,
    )
    assert result.tier in {"mid", "small"}
    assert llm.calls[0]["model"] != "anthropic/claude-opus-5-5"


async def test_structured_retries_with_validation_errors() -> None:
    llm = FakeLLM(
        ['{"supported": "maybe"}', '```json\n{"supported": true, "reason": "quoted"}\n```']
    )
    gateway, records, _ = _gateway(llm)

    result = await gateway.structured(
        purpose="verify-claim",
        messages=[{"role": "user", "content": "Is it supported?"}],
        response_model=Verdict,
        tier="mid",
    )

    assert result.parsed == Verdict(supported=True, reason="quoted")
    assert result.attempts == 2
    assert len(records) == 2
    retry_prompt = llm.calls[1]["messages"][-1]["content"]
    assert "failed validation" in retry_prompt
    assert llm.calls[0]["response_format"]["json_schema"]["name"] == "Verdict"


async def test_structured_gives_up_after_retries() -> None:
    llm = FakeLLM(["not json"] * 3)
    gateway, _, _ = _gateway(llm)

    with pytest.raises(StructuredOutputError, match="Verdict"):
        await gateway.structured(
            purpose="verify-claim",
            messages=[{"role": "user", "content": "?"}],
            response_model=Verdict,
            max_validation_retries=2,
        )
    assert len(llm.calls) == 3


async def test_failed_call_is_recorded_and_reraised() -> None:
    async def broken(**_: Any) -> None:
        raise RuntimeError("provider down")

    records: list[CallRecord] = []
    gateway = LLMGateway(
        settings=Settings(_env_file=None),
        completion_fn=broken,
        tracer=FakeTracer(),
        recorder=records.append,
        budgets=BudgetRegistry(Decimal("1")),
    )
    with pytest.raises(RuntimeError):
        await gateway.complete(purpose="x", messages=[{"role": "user", "content": "hi"}])
    assert records[0].success is False
    assert records[0].error == "provider down"


async def test_no_temperature_by_default_and_unsupported_params_dropped() -> None:
    llm = FakeLLM(["ok", "ok"])
    gateway, _, _ = _gateway(llm)

    await gateway.complete(purpose="x", messages=[{"role": "user", "content": "hi"}])
    await gateway.complete(
        purpose="x", messages=[{"role": "user", "content": "hi"}], temperature=0.7
    )

    assert "temperature" not in llm.calls[0]
    assert llm.calls[0]["drop_params"] is True
    assert llm.calls[1]["temperature"] == 0.7


# --------------------------------------------------------------------------------------
# Real LiteLLM request preparation, no network: LiteLLM's mock_response still runs its
# parameter checks for each model. This catches provider rule changes (for example,
# Claude 5.5 rejecting a custom temperature) that a fake completion function cannot.


@pytest.mark.parametrize("tier", ["frontier", "mid", "small", "judge"])
async def test_every_tier_passes_litellm_parameter_checks(
    tier: Tier, monkeypatch: pytest.MonkeyPatch
) -> None:
    import functools

    import litellm

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    gateway = LLMGateway(
        settings=Settings(_env_file=None),
        completion_fn=functools.partial(
            litellm.acompletion, mock_response='{"supported": true, "reason": "quoted"}'
        ),
        tracer=FakeTracer(),
        budgets=BudgetRegistry(Decimal("1")),
    )

    plain = await gateway.complete(
        purpose="x", messages=[{"role": "user", "content": "hi"}], tier=tier, temperature=0.2
    )
    structured = await gateway.structured(
        purpose="verify-claim",
        messages=[{"role": "user", "content": "Is it supported?"}],
        response_model=Verdict,
        tier=tier,
    )

    assert plain.content
    assert structured.parsed == Verdict(supported=True, reason="quoted")
