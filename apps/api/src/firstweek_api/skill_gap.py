"""Skill gap for a person's background (ADR 0016).

This endpoint spends money (one Claude call) and takes a person's private text, so it is
fenced: the text is length-limited, never stored, and calls are rate limited per client and
per day. Limits are in memory, which is right for one API process; move them to Redis before
running several."""

import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from firstweek_api.reports import published_report_id
from firstweek_core.config import get_settings
from firstweek_core.llm import LLMGateway
from firstweek_core.llm.recorder import record_to_db
from firstweek_research import gap

router = APIRouter(prefix="/roles", tags=["skill-gap"])

MAX_BACKGROUND = 2000
PER_CLIENT = (5, 3600)  # five analyses an hour
PER_DAY = (200, 86400)  # and 200 a day in all: a hard ceiling on spend


class Limiter:
    """Allows `calls` events per `seconds`, remembered in memory."""

    def __init__(self, calls: int, seconds: int, clock: Callable[[], float] = time.monotonic):
        self.calls, self.seconds, self.clock = calls, seconds, clock
        self._seen: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = self.clock()
        seen = self._seen[key]
        while seen and now - seen[0] >= self.seconds:
            seen.popleft()
        if len(seen) >= self.calls:
            return False
        seen.append(now)
        return True


client_limit = Limiter(*PER_CLIENT)
day_limit = Limiter(*PER_DAY)


class GapRequest(BaseModel):
    background: str = Field(min_length=1, max_length=MAX_BACKGROUND)


class GapLine(BaseModel):
    skill_id: str
    label: str
    share: float
    status: str
    reason: str


class GapResponse(BaseModel):
    lines: list[GapLine]
    coverage: float
    model: str


def gateway() -> LLMGateway:
    """Overridden in tests."""
    return LLMGateway(settings=get_settings(), recorder=record_to_db)


@router.post("/{slug}/skill-gap")
async def skill_gap(slug: str, body: GapRequest, request: Request) -> GapResponse:
    """Compare a background with the skills the published report says the role asks for."""
    report_id = published_report_id(slug)
    if report_id is None:
        raise HTTPException(status_code=404, detail="No published report for this role yet.")
    if get_settings().anthropic_api_key is None:
        raise HTTPException(status_code=503, detail="The comparison is not available right now.")
    who = request.client.host if request.client else "unknown"
    if not client_limit.allow(who) or not day_limit.allow("all"):
        raise HTTPException(
            status_code=429, detail="Too many comparisons just now. Try again later."
        )
    try:
        skills = gap.asked_skills(report_id)
        name = _role_name(slug)
        g = gateway()
        try:
            result = await gap.skill_gap(g, name, skills, body.background)
        finally:
            g.flush()
    except gap.GapError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return GapResponse(
        lines=[
            GapLine(
                skill_id=i.skill_id,
                label=result.labels[i.skill_id],
                share=result.shares[i.skill_id],
                status=i.status,
                reason=i.reason,
            )
            for i in result.items
        ],
        coverage=result.coverage,
        model=result.model,
    )


def _role_name(slug: str) -> str:
    from firstweek_api.reports import _newest_published

    found = _newest_published(slug)
    return found[0][0].name if found else slug
