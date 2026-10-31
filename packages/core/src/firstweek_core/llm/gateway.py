"""The one door every model call goes through.

It handles model routing by tier, worst-case budget checks before each call,
cost accounting from our own price table, structured output with validation
retries, tracing, and a record of every call.
"""

import json
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from firstweek_core.config import Settings, get_settings
from firstweek_core.llm.budget import Budget, BudgetExceededError, BudgetRegistry
from firstweek_core.llm.pricing import cost_usd
from firstweek_core.llm.tracing import Tracer, default_tracer

Tier = Literal["frontier", "mid", "small", "judge"]
Message = dict[str, str]
CompletionFn = Callable[..., Awaitable[Any]]

# Cheaper fallbacks used only when a caller allows downgrading.
DOWNGRADE: dict[Tier, Tier | None] = {
    "frontier": "mid",
    "mid": "small",
    "small": None,
    "judge": None,
}

CHARS_PER_TOKEN = 3  # deliberately pessimistic, so pre-call estimates overshoot


class StructuredOutputError(Exception):
    """The model never produced output that validates against the requested schema."""


@dataclass(frozen=True)
class CallRecord:
    purpose: str
    tier: Tier
    model: str
    budget_scope: str
    prompt_version: str | None
    tokens_in: int
    tokens_out: int
    cost_usd: Decimal
    latency_ms: int
    success: bool
    error: str | None
    trace_id: str | None


@dataclass(frozen=True)
class LLMResult[T]:
    content: str
    parsed: T | None
    model: str
    tier: Tier
    tokens_in: int
    tokens_out: int
    cost_usd: Decimal
    latency_ms: int
    attempts: int
    trace_id: str | None = None


Recorder = Callable[[CallRecord], None]


def estimate_tokens(messages: list[Message]) -> int:
    return sum(len(m.get("content", "")) for m in messages) // CHARS_PER_TOKEN + 16 * len(messages)


def _strip_fences(text: str) -> str:
    match = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL)
    return match.group(1).strip() if match else text.strip()


@dataclass
class LLMGateway:
    settings: Settings = field(default_factory=get_settings)
    completion_fn: CompletionFn | None = None
    tracer: Tracer | None = None
    recorder: Recorder | None = None
    budgets: BudgetRegistry | None = None

    def __post_init__(self) -> None:
        self.settings.export_credentials()
        if self.completion_fn is None:
            import litellm

            self.completion_fn = litellm.acompletion
        if self.tracer is None:
            self.tracer = default_tracer(self.settings.tracing_enabled)
        if self.budgets is None:
            self.budgets = BudgetRegistry(Decimal(str(self.settings.default_budget_usd)))

    # ------------------------------------------------------------ routing

    def model_for(self, tier: Tier) -> str:
        return {
            "frontier": self.settings.model_frontier,
            "mid": self.settings.model_mid,
            "small": self.settings.model_small,
            "judge": self.settings.model_judge,
        }[tier]

    def _choose_tier(
        self,
        tier: Tier,
        budget: Budget,
        worst_case: Callable[[str], Decimal],
        allow_downgrade: bool,
    ) -> Tier:
        current: Tier | None = tier
        while current is not None:
            if budget.can_afford(worst_case(self.model_for(current))):
                return current
            current = DOWNGRADE[current] if allow_downgrade else None
        budget.ensure(worst_case(self.model_for(tier)))  # raises with a clear message
        return tier  # pragma: no cover

    # ------------------------------------------------------------ public API

    def budget(self, scope: str, limit_usd: Decimal | None = None) -> Budget:
        """The budget for a scope, created (or its limit changed) on request."""
        assert self.budgets is not None
        return self.budgets.get(scope, limit_usd)

    async def complete(
        self,
        *,
        purpose: str,
        messages: list[Message],
        tier: Tier = "mid",
        budget_scope: str = "default",
        budget_usd: float | None = None,
        max_tokens: int = 2048,
        temperature: float | None = None,
        prompt_version: str | None = None,
        allow_downgrade: bool = False,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResult[None]:
        """One model call, budget-checked, traced and recorded."""
        assert self.budgets is not None and self.tracer is not None and self.completion_fn
        limit = Decimal(str(budget_usd)) if budget_usd is not None else None
        budget = self.budgets.get(budget_scope, limit)
        est_in = estimate_tokens(messages)
        chosen = self._choose_tier(
            tier, budget, lambda model: cost_usd(model, est_in, max_tokens), allow_downgrade
        )
        model = self.model_for(chosen)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "num_retries": 2,
            # Newer models reject some sampling parameters (Claude 5.5 accepts only the
            # default temperature). Drop what a model does not support instead of failing.
            "drop_params": True,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        if response_format is not None:
            kwargs["response_format"] = response_format

        metadata = {"purpose": purpose, "tier": chosen, "budget_scope": budget_scope}
        if prompt_version:
            metadata["prompt_version"] = prompt_version

        started = time.perf_counter()
        with self.tracer.generation(
            name=purpose, model=model, input=messages, metadata=metadata
        ) as gen:
            try:
                response = await self.completion_fn(**kwargs)
            except Exception as exc:
                latency = int((time.perf_counter() - started) * 1000)
                gen.finish(
                    output=None, tokens_in=0, tokens_out=0, cost_usd=Decimal(0), error=str(exc)
                )
                self._record(
                    purpose,
                    chosen,
                    model,
                    budget_scope,
                    prompt_version,
                    0,
                    0,
                    Decimal(0),
                    latency,
                    False,
                    str(exc),
                    gen.trace_id,
                )
                raise
            latency = int((time.perf_counter() - started) * 1000)
            content = response.choices[0].message.content or ""
            tokens_in = int(getattr(response.usage, "prompt_tokens", 0) or 0)
            tokens_out = int(getattr(response.usage, "completion_tokens", 0) or 0)
            cost = cost_usd(model, tokens_in, tokens_out)
            gen.finish(output=content, tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=cost)
            trace_id = gen.trace_id

        budget.record(cost, tokens_in, tokens_out)
        self._record(
            purpose,
            chosen,
            model,
            budget_scope,
            prompt_version,
            tokens_in,
            tokens_out,
            cost,
            latency,
            True,
            None,
            trace_id,
        )
        return LLMResult(
            content=content,
            parsed=None,
            model=model,
            tier=chosen,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
            latency_ms=latency,
            attempts=1,
            trace_id=trace_id,
        )

    async def structured[M: BaseModel](
        self,
        *,
        purpose: str,
        messages: list[Message],
        response_model: type[M],
        max_validation_retries: int = 2,
        **kwargs: Any,
    ) -> LLMResult[M]:
        """A call whose reply must validate against `response_model`.

        On invalid output, the validation errors go back to the model and it tries again.
        """
        schema = response_model.model_json_schema()
        instruction = (
            "Reply with a single JSON object that matches this JSON schema. "
            "No prose and no code fences.\n" + json.dumps(schema)
        )
        convo: list[Message] = [{"role": "system", "content": instruction}, *messages]
        response_format = {
            "type": "json_schema",
            "json_schema": {"name": response_model.__name__, "schema": schema, "strict": False},
        }
        totals_in = totals_out = latency = 0
        total_cost = Decimal(0)
        last_error = ""
        for attempt in range(1, max_validation_retries + 2):
            result = await self.complete(
                purpose=purpose, messages=convo, response_format=response_format, **kwargs
            )
            totals_in += result.tokens_in
            totals_out += result.tokens_out
            total_cost += result.cost_usd
            latency += result.latency_ms
            try:
                parsed = response_model.model_validate_json(_strip_fences(result.content))
            except (ValidationError, ValueError) as exc:
                last_error = str(exc)
                convo = [
                    *convo,
                    {"role": "assistant", "content": result.content},
                    {
                        "role": "user",
                        "content": "That reply failed validation:\n"
                        f"{last_error}\nReply again with corrected JSON only.",
                    },
                ]
                continue
            return LLMResult(
                content=result.content,
                parsed=parsed,
                model=result.model,
                tier=result.tier,
                tokens_in=totals_in,
                tokens_out=totals_out,
                cost_usd=total_cost,
                latency_ms=latency,
                attempts=attempt,
                trace_id=result.trace_id,
            )
        raise StructuredOutputError(
            f"{purpose}: no valid {response_model.__name__} after "
            f"{max_validation_retries + 1} attempts. Last error: {last_error}"
        )

    def flush(self) -> None:
        if self.tracer is not None:
            self.tracer.flush()

    # ------------------------------------------------------------ internals

    def _record(
        self,
        purpose: str,
        tier: Tier,
        model: str,
        scope: str,
        prompt_version: str | None,
        tokens_in: int,
        tokens_out: int,
        cost: Decimal,
        latency_ms: int,
        success: bool,
        error: str | None,
        trace_id: str | None,
    ) -> None:
        if self.recorder is None:
            return
        self.recorder(
            CallRecord(
                purpose=purpose,
                tier=tier,
                model=model,
                budget_scope=scope,
                prompt_version=prompt_version,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=cost,
                latency_ms=latency_ms,
                success=success,
                error=error,
                trace_id=trace_id,
            )
        )


__all__ = [
    "BudgetExceededError",
    "CallRecord",
    "LLMGateway",
    "LLMResult",
    "StructuredOutputError",
    "Tier",
]
