from decimal import Decimal

import pytest

from firstweek_core.llm.budget import BudgetExceededError, BudgetRegistry
from firstweek_core.llm.pricing import FALLBACK_PRICE, cost_usd, is_known, price_for


def test_cost_uses_provider_prefix_free_name() -> None:
    # Opus 5.5: $4 in / $20 out per million tokens
    assert cost_usd("anthropic/claude-opus-5-5", 1_000_000, 100_000) == Decimal("6")


def test_haiku_long_prompt_tier() -> None:
    short = cost_usd("anthropic/claude-haiku-5-5", 100_000, 1_000)
    long = cost_usd("anthropic/claude-haiku-5-5", 100_001, 1_000)
    assert short == Decimal("0.0105")
    assert long > short * 4


def test_unknown_model_is_priced_conservatively() -> None:
    assert not is_known("someone/brand-new-model")
    assert price_for("someone/brand-new-model") == FALLBACK_PRICE


def test_budget_blocks_calls_that_could_overspend() -> None:
    registry = BudgetRegistry(Decimal("1.00"))
    budget = registry.get("sim-123")
    budget.record(Decimal("0.90"), 1000, 100)
    assert budget.can_afford(Decimal("0.10"))
    with pytest.raises(BudgetExceededError, match="sim-123"):
        budget.ensure(Decimal("0.11"))


def test_registry_reuses_scope_and_updates_limit() -> None:
    registry = BudgetRegistry(Decimal("1.00"))
    first = registry.get("research-genai")
    first.record(Decimal("0.25"), 10, 10)
    again = registry.get("research-genai", Decimal("5.00"))
    assert again is first
    assert again.remaining_usd == Decimal("4.75")
