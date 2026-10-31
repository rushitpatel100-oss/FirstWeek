"""Adzuna job search: UK-wide breadth (volume, salaries, locations, employers).

The free API returns only a ~500-character snippet of each description, so these postings
are stored with is_full_text=False. They count towards demand statistics but never count
as evidence that a skill is absent.

Licence: personal and academic research. Adzuna must be credited wherever its data is shown.
"""

from dataclasses import dataclass
from typing import Any

import httpx

from firstweek_research.sources.base import RawPosting, parse_date, request_json, to_decimal

BASE_URL = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"
PAGE_SIZE = 50
CURRENCY = {"gb": "GBP", "us": "USD", "ie": "EUR", "de": "EUR", "fr": "EUR", "nl": "EUR"}
LICENCE = (
    "Adzuna API, personal and academic research licence. Credit Adzuna as the source and "
    "link to adzuna.co.uk wherever this data is shown."
)


@dataclass(frozen=True)
class AdzunaCredentials:
    app_id: str
    app_key: str


def parse_adzuna(item: dict[str, Any], country: str) -> RawPosting:
    location = item.get("location") or {}
    area = location.get("area") or []
    predicted = str(item.get("salary_is_predicted", "0")) == "1"
    return RawPosting(
        provider="adzuna",
        external_id=str(item["id"]),
        url=item["redirect_url"],
        title=item["title"].strip(),
        company=(item.get("company") or {}).get("display_name"),
        department=None,
        locations=tuple(x for x in [location.get("display_name")] if x),
        country_hints=(area[0],) if area else (),
        workplace=None,
        posted_at=parse_date(item.get("created")),
        body_html=None,
        body_text=item.get("description") or "",
        is_full_text=False,
        # Adzuna estimates salaries for some ads; we only keep the ones employers stated.
        salary_min=None if predicted else to_decimal(item.get("salary_min")),
        salary_max=None if predicted else to_decimal(item.get("salary_max")),
        salary_currency=None if predicted else CURRENCY.get(country),
        licence_note=LICENCE,
    )


async def search_adzuna(
    client: httpx.AsyncClient,
    credentials: AdzunaCredentials,
    title_keywords: str,
    *,
    country: str = "gb",
    max_pages: int = 4,
    max_days_old: int = 60,
) -> list[RawPosting]:
    """Postings whose title contains the keywords, newest first, up to max_pages * 50."""
    postings: list[RawPosting] = []
    for page in range(1, max_pages + 1):
        data = await request_json(
            client,
            "GET",
            BASE_URL.format(country=country, page=page),
            params={
                "app_id": credentials.app_id,
                "app_key": credentials.app_key,
                "results_per_page": PAGE_SIZE,
                "title_only": title_keywords,
                "max_days_old": max_days_old,
                "sort_by": "date",
                "content-type": "application/json",
            },
        )
        results = data.get("results") or []
        postings.extend(parse_adzuna(item, country) for item in results)
        if len(results) < PAGE_SIZE:
            break
    return postings
