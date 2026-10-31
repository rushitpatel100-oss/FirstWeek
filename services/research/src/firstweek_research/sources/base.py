"""What every collector returns, plus a polite shared HTTP client."""

import asyncio
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal

import httpx

USER_AGENT = "FirstWeekResearch/0.1 (+https://github.com/rushitpatel100-oss/FirstWeek)"
RETRY_STATUSES = {429, 500, 502, 503, 504}

PostingProvider = Literal["greenhouse", "lever", "ashby", "adzuna"]
Workplace = Literal["onsite", "hybrid", "remote"]


@dataclass(frozen=True)
class RawPosting:
    """One job posting as a provider returned it, before cleaning."""

    provider: PostingProvider
    external_id: str
    url: str
    title: str
    company: str | None
    department: str | None
    locations: tuple[str, ...]
    country_hints: tuple[str, ...]  # structured country fields from the provider, if any
    workplace: Workplace | None
    posted_at: date | None
    body_html: str | None
    body_text: str | None
    is_full_text: bool
    salary_min: Decimal | None
    salary_max: Decimal | None
    salary_currency: str | None
    licence_note: str


@dataclass(frozen=True)
class WebDocument:
    """A blog post, docs page or forum thread found by web search."""

    url: str
    title: str | None
    publisher: str
    markdown: str
    tier: Literal["blog", "forum"]
    query: str
    licence_note: str


class FetchError(Exception):
    pass


def make_client(transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=httpx.Timeout(30.0, connect=10.0),
        follow_redirects=True,
        transport=transport or httpx.AsyncHTTPTransport(retries=2),
    )


async def request_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    attempts: int = 3,
    backoff_s: float = 2.0,
    **kwargs: Any,
) -> Any:
    """JSON request with backoff on rate limits and server errors. Raises FetchError."""
    for attempt in range(1, attempts + 1):
        try:
            response = await client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            if attempt == attempts:
                raise FetchError(f"{method} {url}: {type(exc).__name__}") from exc
        else:
            if response.status_code < 400:
                return response.json()
            if response.status_code not in RETRY_STATUSES or attempt == attempts:
                raise FetchError(f"{method} {url}: HTTP {response.status_code}")
        await asyncio.sleep(backoff_s * attempt)
    raise FetchError(f"{method} {url}: gave up")  # pragma: no cover


def parse_date(value: Any) -> date | None:
    """ISO strings ('2026-09-25T05:17:09-04:00') or epoch milliseconds -> date."""
    if value in (None, ""):
        return None
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value / 1000, tz=UTC).date()
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def to_decimal(value: Any) -> Decimal | None:
    if value in (None, "", 0, "0"):
        return None
    try:
        return Decimal(str(value))
    except ArithmeticError:
        return None
