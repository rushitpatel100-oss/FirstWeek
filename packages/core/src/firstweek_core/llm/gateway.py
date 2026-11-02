"""The one door every model call goes through.

It handles model routing by tier, worst-case budget checks before each call,
cost accounting from our own price table, structured output with validation
retries, tracing, and a record of every call.
"""

import asyncio
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
from firstweek_core.llm.local_embeddings import EmbedKind, embed_local
from firstweek_core.llm.pricing import cost_usd
from firstweek_core.llm.tracing import Tracer, default_tracer

Tier = Literal["frontier", "mid", "small", "judge", "embedding"]
Message = dict[str, str]
CompletionFn = Callable[..., Awaitable[Any]]

# Cheaper fallbacks used only when a caller allows downgrading.
DOWNGRADE: dict[Tier, Tier | None] = {
    "frontier": "mid",
    "mid": "small",
    "small": None,
    "judge": None,
    "embedding": None,
}

CHARS_PER_TOKEN = 3  # deliberately pessimistic, so pre-call estimates overshoot

# Claude 5.5 models think by default, and thinking counts towards max_tokens. A reply that
# runs out of room is retried with a larger limit, up to this ceiling.
MAX_TOKENS_CEILING = 32_000


TRANSIENT_ERRORS = {
    "ServiceUnavailableError",
    "RateLimitError",
    "InternalServerError",
    "BadGatewayError",
    "Timeout",
    "APIConnectionError",
}
TRANSIENT_STATUS = {429, 500, 502, 503, 504}
FREE_TIER_ROUNDS = 4  # passes over the model list before giving up
FREE_TIER_TIMEOUT_S = 120.0  # one call; LiteLLM waits 600s by default, which looks like a hang
FREE_TIER_PAUSE_S = 20.0  # first pause between passes; doubles each time


def is_transient(exc: BaseException) -> bool:
    """A provider hiccup worth waiting out: overloaded, rate limited, unreachable."""
    return (
        type(exc).__name__ in TRANSIENT_ERRORS
        or getattr(exc, "status_code", None) in TRANSIENT_STATUS
    )


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
    # "stop" normally; "length" when the reply hit max_tokens and was cut off.
    finish_reason: str | None = None


Recorder = Callable[[CallRecord], None]
EmbedFn = Callable[[str, list[str], EmbedKind, str], list[list[float]]]


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
    embed_fn: EmbedFn | None = None  # local embedder; tests inject a fake
    sleep_fn: Callable[[float], Awaitable[None]] = asyncio.sleep  # tests skip the waiting

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
            "embedding": self.settings.model_embedding,
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

    async def _call(self, kwargs: dict[str, Any], tier: Tier) -> tuple[Any, str]:
        """One provider call. The free tier waits out overload and falls back to other free
        models; every other tier fails at once, so a paid model is never swapped silently."""
        assert self.completion_fn is not None
        if tier != "judge":
            return await self.completion_fn(**kwargs), str(kwargs["model"])
        # We do the retrying here, so LiteLLM's own quick retries and long default timeout go.
        kwargs = {**kwargs, "timeout": FREE_TIER_TIMEOUT_S, "num_retries": 0}
        models = [str(kwargs["model"]), *self.settings.model_judge_fallbacks]
        pause = FREE_TIER_PAUSE_S
        for attempt in range(FREE_TIER_ROUNDS):
            error: Exception | None = None
            for candidate in models:
                try:
                    return await self.completion_fn(**{**kwargs, "model": candidate}), candidate
                except Exception as exc:
                    # A retired model (404) is skipped like a busy one; the next may work.
                    if not (is_transient(exc) or type(exc).__name__ == "NotFoundError"):
                        raise
                    error = exc
            if attempt == FREE_TIER_ROUNDS - 1 and error is not None:
                raise error
            await self.sleep_fn(pause)
            pause *= 2
        raise AssertionError("unreachable")

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
                response, model = await self._call(kwargs, chosen)
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
            finish_reason = getattr(response.choices[0], "finish_reason", None)
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
            finish_reason=finish_reason,
        )

    async def structured[M: BaseModel](
        self,
        *,
        purpose: str,
        messages: list[Message],
        response_model: type[M],
        max_validation_retries: int = 2,
        max_tokens: int = 2048,
        **kwargs: Any,
    ) -> LLMResult[M]:
        """A call whose reply must validate against `response_model`.

        On invalid output, the validation errors go back to the model and it tries again.
        A reply cut off at max_tokens is not the model's mistake, so it is retried with
        double the limit instead (up to MAX_TOKENS_CEILING).
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
                purpose=purpose,
                messages=convo,
                response_format=response_format,
                max_tokens=max_tokens,
                **kwargs,
            )
            totals_in += result.tokens_in
            totals_out += result.tokens_out
            total_cost += result.cost_usd
            latency += result.latency_ms
            if result.finish_reason == "length":
                last_error = f"reply cut off at max_tokens={max_tokens}"
                if max_tokens >= MAX_TOKENS_CEILING:
                    break
                max_tokens = min(max_tokens * 2, MAX_TOKENS_CEILING)
                continue
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
            f"{attempt} attempts. Last error: {last_error}"
        )

    async def embed(
        self,
        texts: list[str],
        *,
        kind: EmbedKind,
        purpose: str,
        budget_scope: str = "default",
    ) -> list[list[float]]:
        """Embeddings for a batch of texts, recorded as one call.

        "local/<name>" models run on this machine for free; other model strings go through
        LiteLLM and are budget-checked and priced like any other call."""
        assert self.budgets is not None
        model = self.model_for("embedding")
        budget = self.budgets.get(budget_scope)
        started = time.perf_counter()
        tokens_in = sum(len(t) for t in texts) // CHARS_PER_TOKEN
        cost = Decimal(0)
        try:
            if model.startswith("local/"):
                embed_fn = self.embed_fn or embed_local
                vectors = await asyncio.to_thread(
                    embed_fn,
                    model.removeprefix("local/"),
                    texts,
                    kind,
                    self.settings.model_cache_dir,
                )
            else:
                import litellm

                budget.ensure(cost_usd(model, tokens_in, 0))
                response = await litellm.aembedding(model=model, input=texts)
                vectors = [list(item["embedding"]) for item in response.data]
                tokens_in = int(getattr(response.usage, "prompt_tokens", tokens_in) or tokens_in)
                cost = cost_usd(model, tokens_in, 0)
                budget.record(cost, tokens_in, 0)
        except Exception as exc:
            latency = int((time.perf_counter() - started) * 1000)
            self._record(
                purpose,
                "embedding",
                model,
                budget_scope,
                None,
                0,
                0,
                Decimal(0),
                latency,
                False,
                str(exc),
                None,
            )
            raise
        latency = int((time.perf_counter() - started) * 1000)
        self._record(
            purpose,
            "embedding",
            model,
            budget_scope,
            None,
            tokens_in,
            0,
            cost,
            latency,
            True,
            None,
            None,
        )
        return vectors

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
