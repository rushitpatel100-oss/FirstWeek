"""Our own price table, so budgets never depend on a library knowing new models.

Prices are USD per million tokens, from the providers' published pricing (October 2026).
Unknown models are priced like the most expensive known model, so budgets err on the safe side.
"""

from dataclasses import dataclass
from decimal import Decimal

MILLION = Decimal(1_000_000)


@dataclass(frozen=True)
class Price:
    input_per_mtok: Decimal
    output_per_mtok: Decimal
    # Some models charge more once a single prompt passes a size threshold.
    long_prompt_threshold: int | None = None
    long_input_per_mtok: Decimal | None = None
    long_output_per_mtok: Decimal | None = None


PRICES: dict[str, Price] = {
    "claude-opus-5-5": Price(Decimal("4"), Decimal("20")),
    "claude-sonnet-5-5": Price(Decimal("2"), Decimal("10")),
    "claude-haiku-5-5": Price(
        Decimal("0.10"),
        Decimal("0.50"),
        long_prompt_threshold=100_000,
        long_input_per_mtok=Decimal("0.50"),
        long_output_per_mtok=Decimal("2.50"),
    ),
    "gpt-6-sol": Price(Decimal("2"), Decimal("10")),
    "text-embedding-3-small": Price(Decimal("0.02"), Decimal("0")),
    # Gemini models on Google's free tier cost nothing (rate-limited). If you turn on billing
    # for the key, replace these with the paid prices so budgets stay honest.
    "gemini-3.8-flash": Price(Decimal("0"), Decimal("0")),
    "gemini-3.6-flash": Price(Decimal("0"), Decimal("0")),
    "gemini-2.5-flash": Price(Decimal("0"), Decimal("0")),
}

FALLBACK_PRICE = Price(Decimal("10"), Decimal("50"))  # priced like a top-tier model


def _bare_name(model: str) -> str:
    """'anthropic/claude-opus-5-5' -> 'claude-opus-5-5'."""
    return model.rsplit("/", 1)[-1]


def price_for(model: str) -> Price:
    return PRICES.get(_bare_name(model), FALLBACK_PRICE)


def is_known(model: str) -> bool:
    return _bare_name(model) in PRICES


def cost_usd(model: str, tokens_in: int, tokens_out: int) -> Decimal:
    price = price_for(model)
    in_rate, out_rate = price.input_per_mtok, price.output_per_mtok
    if (
        price.long_prompt_threshold is not None
        and tokens_in > price.long_prompt_threshold
        and price.long_input_per_mtok is not None
        and price.long_output_per_mtok is not None
    ):
        in_rate, out_rate = price.long_input_per_mtok, price.long_output_per_mtok
    return (Decimal(tokens_in) * in_rate + Decimal(tokens_out) * out_rate) / MILLION
