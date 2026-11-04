"""How much of today's free model quota is left, from our own call records.

Gemini's free tier allows a fixed number of requests a day per model, reset at midnight Pacific
time; Groq's free tier allows far more. We count our own successful calls since the last reset.
Calls made outside this app (for example in AI Studio) are not seen, so the count is a floor."""

from collections.abc import Mapping
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from firstweek_core.config import Settings
from firstweek_core.db.models import LLMCall
from firstweek_core.db.session import session_scope

FREE_DAILY_REQUESTS = {"gemini": 20, "groq": 1_000}  # per model, free tier
# Groq's free tier also caps tokens a day (prompt plus reply); that runs out long before its
# requests do, so its calls are counted as what the tokens left can pay for.
FREE_DAILY_TOKENS = {"groq": 200_000}
TOKENS_PER_CALL = 10_000  # a generous average for an autopilot call, prompt plus reply
RESET_ZONE = ZoneInfo("America/Los_Angeles")


def window_start(now: datetime | None = None) -> datetime:
    """When today's free quota began: the last midnight in Pacific time, in UTC."""
    local = (now or datetime.now(UTC)).astimezone(RESET_ZONE)
    return datetime.combine(local.date(), time(0), RESET_ZONE).astimezone(UTC)


def next_reset(now: datetime | None = None) -> datetime:
    return window_start(now) + timedelta(days=1)


def free_models(settings: Settings) -> list[str]:
    return [settings.model_local or settings.model_judge, *settings.judge_fallbacks()]


UNLIMITED = 1_000_000  # a model on this machine has no daily limit


def daily_limit(model: str) -> int:
    if model.startswith("ollama/"):
        return UNLIMITED
    return FREE_DAILY_REQUESTS.get(model.split("/")[0], 0)


def remaining(
    settings: Settings, used: Mapping[str, int], tokens: Mapping[str, int] | None = None
) -> dict[str, int]:
    """Calls left today for each free model: requests left, or what the tokens left can pay
    for when the model also has a daily token cap, whichever is smaller."""
    out: dict[str, int] = {}
    for m in free_models(settings):
        calls = max(0, daily_limit(m) - used.get(m, 0))
        cap = FREE_DAILY_TOKENS.get(m.split("/")[0])
        if cap is not None:
            calls = min(calls, max(0, cap - (tokens or {}).get(m, 0)) // TOKENS_PER_CALL)
        out[m] = calls
    return out


def used_today(
    models: list[str], now: datetime | None = None
) -> tuple[dict[str, int], dict[str, int]]:
    """Our successful calls, and the tokens they used, per model since the last reset."""
    since = window_start(now)
    with session_scope() as session:
        rows = session.execute(
            select(
                LLMCall.model,
                func.count(),
                func.coalesce(func.sum(LLMCall.tokens_in + LLMCall.tokens_out), 0),
            )
            .where(LLMCall.model.in_(models), LLMCall.success, LLMCall.created_at >= since)
            .group_by(LLMCall.model)
        ).all()
    calls = {str(model): int(count) for model, count, _ in rows}
    tokens = {str(model): int(total) for model, _, total in rows}
    return calls, tokens
