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
RESET_ZONE = ZoneInfo("America/Los_Angeles")


def window_start(now: datetime | None = None) -> datetime:
    """When today's free quota began: the last midnight in Pacific time, in UTC."""
    local = (now or datetime.now(UTC)).astimezone(RESET_ZONE)
    return datetime.combine(local.date(), time(0), RESET_ZONE).astimezone(UTC)


def next_reset(now: datetime | None = None) -> datetime:
    return window_start(now) + timedelta(days=1)


def free_models(settings: Settings) -> list[str]:
    return [settings.model_judge, *settings.judge_fallbacks()]


def daily_limit(model: str) -> int:
    return FREE_DAILY_REQUESTS.get(model.split("/")[0], 0)


def remaining(settings: Settings, used: Mapping[str, int]) -> dict[str, int]:
    """Requests left today for each free model, given how many were used."""
    return {m: max(0, daily_limit(m) - used.get(m, 0)) for m in free_models(settings)}


def used_today(models: list[str], now: datetime | None = None) -> dict[str, int]:
    """Our successful calls to each model since the last reset."""
    since = window_start(now)
    with session_scope() as session:
        rows = session.execute(
            select(LLMCall.model, func.count())
            .where(LLMCall.model.in_(models), LLMCall.success, LLMCall.created_at >= since)
            .group_by(LLMCall.model)
        ).all()
    return {str(model): int(count) for model, count in rows}
