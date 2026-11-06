"""Gateway tests. None of them call a real model, so they cost nothing and need no keys."""

from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel, SecretStr

from firstweek_core.config import Settings
from firstweek_core.llm import (
    BudgetExceededError,
    BudgetRegistry,
    CallRecord,
    FreeQuotaExhaustedError,
    LLMGateway,
    StructuredOutputError,
    Tier,
)
from firstweek_core.llm.gateway import fit_reply_room, is_daily_quota


def _response(
    content: str, tokens_in: int = 1000, tokens_out: int = 200, finish_reason: str = "stop"
) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(message=SimpleNamespace(content=content), finish_reason=finish_reason)
        ],
        usage=SimpleNamespace(prompt_tokens=tokens_in, completion_tokens=tokens_out),
    )


CUT_OFF = "<cut off>"  # a reply prefixed with this comes back with finish_reason="length"


class FakeLLM:
    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        if reply.startswith(CUT_OFF):
            return _response(reply.removeprefix(CUT_OFF), finish_reason="length")
        return _response(reply)


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


async def test_cut_off_reply_is_retried_with_more_room() -> None:
    # Seen live on 2026-10-31: Claude Haiku 5.5 thinks by default, thinking counts towards
    # max_tokens, and a 400-token limit cut the JSON off mid-string on all three attempts.
    llm = FakeLLM(
        [f'{CUT_OFF}{{"supported": true, "rea', '{"supported": true, "reason": "quoted"}']
    )
    gateway, records, _ = _gateway(llm)

    result = await gateway.structured(
        purpose="verify-claim",
        messages=[{"role": "user", "content": "Is it supported?"}],
        response_model=Verdict,
        tier="small",
        max_tokens=400,
    )

    assert result.parsed == Verdict(supported=True, reason="quoted")
    assert [c["max_tokens"] for c in llm.calls] == [400, 800]
    # The cut-off text is not sent back as if the model had made a mistake.
    assert llm.calls[1]["messages"] == llm.calls[0]["messages"]
    assert len(records) == 2


async def test_cut_off_stops_at_the_ceiling() -> None:
    llm = FakeLLM([f"{CUT_OFF}{{"] * 3)
    gateway, _, _ = _gateway(llm, limit="5")

    with pytest.raises(StructuredOutputError, match="cut off at max_tokens=32000"):
        await gateway.structured(
            purpose="verify-claim",
            messages=[{"role": "user", "content": "?"}],
            response_model=Verdict,
            max_tokens=16_000,
        )
    assert [c["max_tokens"] for c in llm.calls] == [16_000, 32_000]


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


# ---------------------------------------------------------------- embeddings


def _embed_gateway(
    model: str, limit: str = "1.00"
) -> tuple[LLMGateway, list[CallRecord], list[tuple[str, list[str], str, str]]]:
    records: list[CallRecord] = []
    calls: list[tuple[str, list[str], str, str]] = []

    def fake_embed(name: str, texts: list[str], kind: str, cache_dir: str) -> list[list[float]]:
        calls.append((name, texts, kind, cache_dir))
        return [[float(len(t)), 1.0] for t in texts]

    gateway = LLMGateway(
        settings=Settings(_env_file=None, model_embedding=model, model_cache_dir="/models"),
        completion_fn=FakeLLM([]),
        tracer=FakeTracer(),
        recorder=records.append,
        budgets=BudgetRegistry(Decimal(limit)),
        embed_fn=fake_embed,
    )
    return gateway, records, calls


async def test_local_embeddings_are_free_and_recorded() -> None:
    gateway, records, calls = _embed_gateway("local/BAAI/bge-small-en-v1.5")
    vectors = await gateway.embed(["abc", "hello"], kind="query", purpose="search-evidence")
    assert vectors == [[3.0, 1.0], [5.0, 1.0]]
    assert calls == [("BAAI/bge-small-en-v1.5", ["abc", "hello"], "query", "/models")]
    [record] = records
    assert (record.tier, record.model, record.purpose) == (
        "embedding",
        "local/BAAI/bge-small-en-v1.5",
        "search-evidence",
    )
    assert record.cost_usd == 0 and record.success


async def test_hosted_embeddings_are_priced_and_budgeted(monkeypatch: pytest.MonkeyPatch) -> None:
    import litellm

    async def fake_aembedding(model: str, input: list[str]) -> SimpleNamespace:
        return SimpleNamespace(
            data=[{"embedding": [0.1, 0.2]} for _ in input],
            usage=SimpleNamespace(prompt_tokens=1_000_000),
        )

    monkeypatch.setattr(litellm, "aembedding", fake_aembedding)
    gateway, records, calls = _embed_gateway("openai/text-embedding-3-small")
    vectors = await gateway.embed(["a", "b"], kind="passage", purpose="embed-passages")
    assert vectors == [[0.1, 0.2], [0.1, 0.2]] and calls == []  # the local model is not used
    assert records[0].cost_usd == Decimal("0.02")  # a million tokens at $0.02


async def test_a_failed_embedding_is_recorded_and_reraised() -> None:
    gateway, records, _ = _embed_gateway("local/BAAI/bge-small-en-v1.5")

    def broken(name: str, texts: list[str], kind: str, cache_dir: str) -> list[list[float]]:
        raise OSError("model download failed")

    gateway.embed_fn = broken
    with pytest.raises(OSError, match="download"):
        await gateway.embed(["a"], kind="passage", purpose="embed-passages")
    assert not records[0].success and "download" in (records[0].error or "")


def test_bge_queries_carry_the_search_instruction(monkeypatch: pytest.MonkeyPatch) -> None:
    from firstweek_core.llm import local_embeddings

    seen: list[str] = []

    class FakeModel:
        def embed(self, texts: list[str]) -> list[list[float]]:
            seen.extend(texts)
            return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(local_embeddings, "_model", lambda name, cache_dir: FakeModel())
    local_embeddings.embed_local("BAAI/bge-small-en-v1.5", ["evals?"], "query", "/m")
    local_embeddings.embed_local("BAAI/bge-small-en-v1.5", ["We run evals."], "passage", "/m")
    local_embeddings.embed_local("other/model", ["evals?"], "query", "/m")
    assert seen == [
        "Represent this sentence for searching relevant passages: evals?",
        "We run evals.",
        "evals?",
    ]


class OverloadedError(Exception):
    """Named like litellm's error so the gateway treats it as a provider hiccup."""


OverloadedError.__name__ = "ServiceUnavailableError"


class RetiredError(Exception):
    """Named like litellm's 404 error: the model no longer exists."""


RetiredError.__name__ = "NotFoundError"


class Flaky:
    def __init__(self, failing_models: set[str], fail_times: int = 99) -> None:
        self.failing, self.fail_times = failing_models, fail_times
        self.models: list[str] = []

    async def __call__(self, **kwargs: Any) -> SimpleNamespace:
        self.models.append(kwargs["model"])
        if kwargs["model"] in self.failing and self.fail_times > 0:
            self.fail_times -= 1
            raise OverloadedError("503 high demand")
        return _response("ok")


def _free_gateway(llm: Flaky, sleeps: list[float]) -> LLMGateway:
    async def no_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    return LLMGateway(
        settings=Settings(_env_file=None),
        completion_fn=llm,
        tracer=FakeTracer(),
        recorder=lambda _: None,
        budgets=BudgetRegistry(Decimal("1")),
        sleep_fn=no_sleep,
    )


async def test_an_overloaded_free_model_falls_back_to_the_next_free_one() -> None:
    settings = Settings(_env_file=None)
    llm = Flaky({settings.model_judge})
    result = await _free_gateway(llm, []).complete(
        purpose="x", messages=[{"role": "user", "content": "hi"}], tier="judge"
    )
    assert llm.models == [settings.model_judge, settings.model_judge_fallbacks[0]]
    assert result.model == settings.model_judge_fallbacks[0]


async def test_when_every_free_model_is_busy_it_waits_with_growing_pauses_then_gives_up() -> None:
    settings = Settings(_env_file=None)
    llm = Flaky({settings.model_judge, *settings.model_judge_fallbacks})
    sleeps: list[float] = []
    with pytest.raises(OverloadedError):
        await _free_gateway(llm, sleeps).complete(
            purpose="x", messages=[{"role": "user", "content": "hi"}], tier="judge"
        )
    assert sleeps == [20.0, 40.0, 80.0]
    assert len(llm.models) == 2 * 4  # two models, four passes


async def test_the_free_tier_recovers_after_a_pause() -> None:
    settings = Settings(_env_file=None)
    llm = Flaky({settings.model_judge, *settings.model_judge_fallbacks}, fail_times=3)
    sleeps: list[float] = []
    result = await _free_gateway(llm, sleeps).complete(
        purpose="x", messages=[{"role": "user", "content": "hi"}], tier="judge"
    )
    assert sleeps == [20.0] and result.content == "ok"


async def test_a_retired_free_model_is_skipped_and_calls_get_a_short_timeout() -> None:
    settings = Settings(_env_file=None)
    seen: list[dict[str, Any]] = []

    async def llm(**kwargs: Any) -> SimpleNamespace:
        seen.append(kwargs)
        if kwargs["model"] == settings.model_judge:
            raise RetiredError("404 no longer available")
        return _response("ok")

    gateway = _free_gateway(Flaky(set()), [])
    gateway.completion_fn = llm
    result = await gateway.complete(
        purpose="x", messages=[{"role": "user", "content": "hi"}], tier="judge"
    )
    assert result.model == settings.model_judge_fallbacks[0]
    assert seen[0]["timeout"] == 120.0 and seen[0]["num_retries"] == 0


async def test_a_paid_tier_never_falls_back_or_waits() -> None:
    llm = Flaky({"anthropic/claude-sonnet-5-5"})
    sleeps: list[float] = []
    with pytest.raises(OverloadedError):
        await _free_gateway(llm, sleeps).complete(
            purpose="x", messages=[{"role": "user", "content": "hi"}], tier="mid"
        )
    assert llm.models == ["anthropic/claude-sonnet-5-5"] and sleeps == []


async def test_an_error_that_is_not_a_hiccup_is_raised_at_once() -> None:
    async def broken(**_: Any) -> None:
        raise ValueError("bad request")

    gateway = LLMGateway(
        settings=Settings(_env_file=None),
        completion_fn=broken,
        tracer=FakeTracer(),
        recorder=lambda _: None,
        budgets=BudgetRegistry(Decimal("1")),
    )
    with pytest.raises(ValueError):
        await gateway.complete(
            purpose="x", messages=[{"role": "user", "content": "hi"}], tier="judge"
        )


class DailyQuotaError(Exception):
    pass


DailyQuotaError.__name__ = "RateLimitError"


async def test_a_spent_daily_quota_is_not_retried_and_fails_at_once_when_all_are_spent() -> None:
    settings = Settings(_env_file=None)
    seen: list[str] = []

    async def llm(**kwargs: Any) -> SimpleNamespace:
        seen.append(kwargs["model"])
        raise DailyQuotaError("limit exceeded GenerateRequestsPerDayPerProjectPerModel-FreeTier")

    sleeps: list[float] = []
    gateway = _free_gateway(Flaky(set()), sleeps)
    gateway.completion_fn = llm
    with pytest.raises(FreeQuotaExhaustedError) as raised:
        await gateway.complete(
            purpose="x", messages=[{"role": "user", "content": "hi"}], tier="judge"
        )
    assert isinstance(raised.value.__cause__, DailyQuotaError)
    assert seen == [settings.model_judge, *settings.model_judge_fallbacks]  # each asked once
    assert sleeps == []


def test_groq_joins_the_free_chain_only_when_its_key_is_set() -> None:
    without = Settings(_env_file=None, gemini_api_key=SecretStr("g"))
    assert without.judge_fallbacks() == without.model_judge_fallbacks
    with_groq = Settings(_env_file=None, groq_api_key=SecretStr("k"))
    assert with_groq.judge_fallbacks() == [*with_groq.model_judge_fallbacks, with_groq.model_groq]
    assert with_groq.has_judge_key and not Settings(_env_file=None).has_judge_key


def test_groq_daily_limits_are_recognised_as_spent_for_the_day() -> None:
    assert is_daily_quota(Exception("Rate limit reached ... on tokens per day (TPD): Limit 200000"))
    assert not is_daily_quota(Exception("Rate limit reached ... on tokens per minute (TPM)"))


class DisguisedQuotaError(Exception):
    pass


DisguisedQuotaError.__name__ = "BadRequestError"


async def test_a_gemini_429_wrapped_as_a_bad_request_still_falls_back_to_the_next_model() -> None:
    settings = Settings(_env_file=None, groq_api_key=SecretStr("k"))
    seen: list[str] = []

    async def llm(**kwargs: Any) -> SimpleNamespace:
        seen.append(kwargs["model"])
        if kwargs["model"].startswith("gemini/"):
            raise DisguisedQuotaError(
                'GeminiException BadRequestError - {"error": {"code": 429, "status": '
                '"RESOURCE_EXHAUSTED", "message": "Generate content requests per day limit '
                'exceeded on Free Tier"}}'
            )
        return _response("from groq")

    sleeps: list[float] = []
    gateway = _free_gateway(Flaky(set()), sleeps)
    gateway.settings = settings
    gateway.completion_fn = llm
    result = await gateway.complete(
        purpose="x", messages=[{"role": "user", "content": "hi"}], tier="judge"
    )
    assert result.model == settings.model_groq and result.content == "from groq"
    assert seen == [settings.model_judge, *settings.model_judge_fallbacks, settings.model_groq]
    assert sleeps == []  # a daily quota is not worth waiting for


def test_every_model_in_the_free_chain_has_a_price_so_budgets_stay_honest() -> None:
    from firstweek_core.llm.pricing import cost_usd, is_known

    settings = Settings(_env_file=None, groq_api_key=SecretStr("k"))
    chain = [settings.model_judge, *settings.judge_fallbacks()]
    assert all(is_known(model) for model in chain)  # an unknown model is priced as top-tier
    assert all(cost_usd(model, 100_000, 10_000) == 0 for model in chain)


def test_a_groq_call_is_sized_to_fit_its_tokens_per_minute_cap() -> None:
    small = [{"role": "user", "content": "x" * 8_000}]  # about 2,000 tokens
    assert fit_reply_room("groq/openai/gpt-oss-120b", small, 8_000) == 8_000 - 2_000 - 300
    assert fit_reply_room("gemini/gemini-3.8-flash", small, 8_000) == 8_000
    huge = [{"role": "user", "content": "x" * 30_000}]  # about 7,500 tokens: no room to reply
    assert fit_reply_room("groq/openai/gpt-oss-120b", huge, 8_000) is None


async def test_a_prompt_too_large_for_groq_skips_it_instead_of_failing() -> None:
    seen: list[tuple[str, int]] = []

    async def llm(**kwargs: Any) -> SimpleNamespace:
        seen.append((kwargs["model"], kwargs["max_tokens"]))
        if kwargs["model"].startswith("gemini"):
            raise DailyQuotaError(
                "limit exceeded GenerateRequestsPerDayPerProjectPerModel-FreeTier"
            )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"), finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        )

    gateway = _free_gateway(Flaky(set()), [])
    gateway.settings = Settings(_env_file=None, groq_api_key=SecretStr("k"))
    gateway.completion_fn = llm
    result = await gateway.complete(
        purpose="x", messages=[{"role": "user", "content": "x" * 8_000}], tier="judge",
        max_tokens=8_000,
    )  # fmt: skip
    assert result.content == "ok"
    assert seen[-1] == ("groq/openai/gpt-oss-120b", 8_000 - 2_000 - 300)


def test_the_free_quota_left_is_counted_per_model_from_the_last_pacific_midnight() -> None:
    from datetime import UTC, datetime

    from firstweek_core.llm import quota

    # 09:00 in London on 3 November is 01:00 Pacific: the day began at 08:00 UTC.
    assert quota.window_start(datetime(2026, 11, 3, 9, tzinfo=UTC)) == datetime(
        2026, 11, 3, 8, tzinfo=UTC
    )
    # 07:00 UTC is still the previous Pacific day.
    assert quota.window_start(datetime(2026, 11, 3, 7, tzinfo=UTC)).day == 2
    settings = Settings(_env_file=None, groq_api_key=SecretStr("k"))
    left = quota.remaining(settings, {settings.model_judge: 18})
    assert left[settings.model_judge] == 2
    assert left[settings.model_judge_fallbacks[0]] == 20
    assert left[settings.model_groq] == 20  # 200,000 tokens a day at 10,000 a call
    spent = quota.remaining(settings, {settings.model_groq: 33}, {settings.model_groq: 170_000})
    assert spent[settings.model_groq] == 3  # its tokens run out long before its requests


async def test_when_gemini_is_spent_and_the_prompt_is_too_big_for_groq_the_run_pauses() -> None:
    async def llm(**kwargs: Any) -> SimpleNamespace:
        raise DailyQuotaError("limit exceeded GenerateRequestsPerDayPerProjectPerModel-FreeTier")

    sleeps: list[float] = []
    gateway = _free_gateway(Flaky(set()), sleeps)
    gateway.settings = Settings(_env_file=None, groq_api_key=SecretStr("k"))
    gateway.completion_fn = llm
    with pytest.raises(FreeQuotaExhaustedError):
        await gateway.complete(
            purpose="x", messages=[{"role": "user", "content": "x" * 40_000}], tier="judge"
        )
    assert sleeps == []  # no pointless waiting


def test_a_probe_failure_says_why_the_model_refused() -> None:
    from firstweek_core.llm.gateway import probe_status

    assert probe_status(
        DailyQuotaError('quota_id: "GenerateRequestsPerDayPerProjectPerModel"')
    ) == ("spent for today")
    assert probe_status(DailyQuotaError('"quotaValue": "0", "limit": 0')) == "no free tier"
    assert probe_status(DailyQuotaError("GenerateRequestsPerMinutePerProjectPerModel")) == (
        "busy this minute"
    )
    assert probe_status(DailyQuotaError("You exceeded your current quota")) == (
        "refused (429 or overloaded)"
    )


async def test_a_probe_asks_one_model_once_with_no_fallback() -> None:
    seen: list[str] = []

    async def llm(**kwargs: Any) -> SimpleNamespace:
        seen.append(kwargs["model"])
        raise DailyQuotaError("GenerateRequestsPerDayPerProjectPerModel-FreeTier")

    records: list[Any] = []
    gateway = _free_gateway(Flaky(set()), [])
    gateway.completion_fn = llm
    gateway.recorder = records.append
    assert await gateway.probe("gemini/gemini-3.8-flash") == "spent for today"
    assert seen == ["gemini/gemini-3.8-flash"]
    assert records[0].purpose == "quota-probe" and records[0].success is False


async def test_a_local_model_is_tried_first_with_its_address_and_no_cost() -> None:
    seen: list[dict[str, Any]] = []

    async def llm(**kwargs: Any) -> SimpleNamespace:
        seen.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=SimpleNamespace(prompt_tokens=3, completion_tokens=1),
        )

    records: list[CallRecord] = []
    settings = Settings(_env_file=None, model_local="ollama/qwen2.5-coder:7b")
    gateway = LLMGateway(
        settings=settings, completion_fn=llm, tracer=FakeTracer(),
        recorder=records.append, budgets=BudgetRegistry(Decimal("1")),
    )  # fmt: skip
    assert settings.has_judge_key
    assert settings.judge_fallbacks()[0] == settings.model_judge
    await gateway.complete(purpose="t", messages=[{"role": "user", "content": "hi"}], tier="judge")
    assert seen[0]["model"] == "ollama/qwen2.5-coder:7b"
    assert seen[0]["api_base"] == settings.ollama_api_base
    assert seen[0]["num_ctx"] == settings.ollama_num_ctx
    assert records[0].cost_usd == 0


def test_a_local_model_has_no_daily_limit() -> None:
    from firstweek_core.llm import quota

    settings = Settings(_env_file=None, model_local="ollama/qwen2.5-coder:7b")
    left = quota.remaining(settings, {}, {})
    assert left["ollama/qwen2.5-coder:7b"] == quota.UNLIMITED


async def test_a_probe_of_a_local_model_sends_one_timeout() -> None:
    seen: list[dict[str, Any]] = []

    async def llm(**kwargs: Any) -> SimpleNamespace:
        seen.append(kwargs)
        return SimpleNamespace()

    gateway = _free_gateway(Flaky(set()), [])
    gateway.completion_fn = llm
    assert await gateway.probe("ollama/qwen2.5-coder:7b") == "ok"
    assert seen[0]["api_base"] and seen[0]["timeout"] > 30


async def test_a_local_model_is_not_sent_a_reasoning_effort() -> None:
    seen: list[dict[str, Any]] = []

    async def llm(**kwargs: Any) -> SimpleNamespace:
        seen.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=SimpleNamespace(prompt_tokens=3, completion_tokens=1),
        )

    settings = Settings(_env_file=None, model_local="ollama/qwen2.5-coder:7b")
    gateway = LLMGateway(
        settings=settings, completion_fn=llm, tracer=FakeTracer(),
        recorder=lambda _: None, budgets=BudgetRegistry(Decimal("1")),
    )  # fmt: skip
    await gateway.complete(purpose="t", messages=[{"role": "user", "content": "hi"}], tier="judge")
    assert "reasoning_effort" not in seen[0]
