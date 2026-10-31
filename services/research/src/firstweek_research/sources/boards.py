"""Company job boards: Greenhouse, Lever and Ashby public posting APIs.

These are the APIs companies use to show openings on their own careers pages. They return
full posting text, so they are our main source for skill statistics.
"""

import asyncio
import html
from functools import cache
from importlib import resources
from typing import Any, Literal

import httpx
import yaml
from pydantic import BaseModel

from firstweek_research.sources.base import (
    FetchError,
    RawPosting,
    Workplace,
    parse_date,
    request_json,
    to_decimal,
)

Ats = Literal["greenhouse", "lever", "ashby"]


class BoardConfig(BaseModel):
    company: str
    ats: Ats
    token: str
    region: Literal["global", "eu"] = "global"  # Lever has a separate EU instance

    @property
    def url(self) -> str:
        if self.ats == "greenhouse":
            return f"https://boards-api.greenhouse.io/v1/boards/{self.token}/jobs?content=true"
        if self.ats == "lever":
            host = "api.eu.lever.co" if self.region == "eu" else "api.lever.co"
            return f"https://{host}/v0/postings/{self.token}?mode=json"
        return (
            f"https://api.ashbyhq.com/posting-api/job-board/{self.token}?includeCompensation=true"
        )

    @property
    def licence_note(self) -> str:
        return (
            f"Public {self.ats.title()} job-board API, published by {self.company} for display "
            "of its openings. Used for aggregate research; link back to the original posting."
        )


@cache
def load_boards() -> list[BoardConfig]:
    path = resources.files("firstweek_research") / "data" / "sources" / "job_boards.yaml"
    data = yaml.safe_load(path.read_text("utf-8"))
    return [BoardConfig.model_validate(b) for b in data["boards"]]


def _workplace(value: str | None) -> Workplace | None:
    v = (value or "").lower().replace("-", "").replace(" ", "")
    if v in {"onsite", "inoffice", "office"}:
        return "onsite"
    if v in {"hybrid", "remote"}:
        return v  # type: ignore[return-value]
    return None


def parse_greenhouse(data: dict[str, Any], board: BoardConfig) -> list[RawPosting]:
    postings = []
    for job in data.get("jobs", []):
        location = (job.get("location") or {}).get("name") or ""
        offices = [o.get("name", "") for o in job.get("offices") or [] if o.get("name")]
        departments = [d.get("name") for d in job.get("departments") or [] if d.get("name")]
        postings.append(
            RawPosting(
                provider="greenhouse",
                external_id=f"{board.token}:{job['id']}",
                url=job["absolute_url"],
                title=job["title"].strip(),
                company=(job.get("company_name") or board.company).strip(),
                department=departments[0] if departments else None,
                locations=tuple(x for x in [location, *offices] if x),
                country_hints=(),
                workplace=_workplace("remote" if "remote" in location.lower() else None),
                posted_at=parse_date(job.get("first_published") or job.get("updated_at")),
                # Greenhouse returns the HTML entity-escaped.
                body_html=html.unescape(job.get("content") or ""),
                body_text=None,
                is_full_text=True,
                salary_min=None,
                salary_max=None,
                salary_currency=None,
                licence_note=board.licence_note,
            )
        )
    return postings


def parse_lever(data: list[dict[str, Any]], board: BoardConfig) -> list[RawPosting]:
    postings = []
    for job in data:
        cats = job.get("categories") or {}
        locations = cats.get("allLocations") or [cats.get("location")]
        sections = [job.get("descriptionBody") or job.get("description") or ""]
        for block in job.get("lists") or []:
            sections.append(f"<h3>{block.get('text', '')}</h3><ul>{block.get('content', '')}</ul>")
        sections.append(job.get("additional") or "")
        salary = job.get("salaryRange") or {}
        postings.append(
            RawPosting(
                provider="lever",
                external_id=f"{board.token}:{job['id']}",
                url=job["hostedUrl"],
                title=job["text"].strip(),
                company=board.company,
                department=cats.get("department") or cats.get("team"),
                locations=tuple(x for x in locations if x),
                country_hints=(job["country"],) if job.get("country") else (),
                workplace=_workplace(job.get("workplaceType")),
                posted_at=parse_date(job.get("createdAt")),
                body_html="\n".join(sections),
                body_text=None,
                is_full_text=True,
                salary_min=to_decimal(salary.get("min")),
                salary_max=to_decimal(salary.get("max")),
                salary_currency=salary.get("currency"),
                licence_note=board.licence_note,
            )
        )
    return postings


def _ashby_salary(job: dict[str, Any]) -> tuple[Any, Any, str | None]:
    for comp in (job.get("compensation") or {}).get("summaryComponents") or []:
        if comp.get("compensationType") == "Salary" and comp.get("interval") == "1 YEAR":
            return comp.get("minValue"), comp.get("maxValue"), comp.get("currencyCode")
    return None, None, None


def parse_ashby(data: dict[str, Any], board: BoardConfig) -> list[RawPosting]:
    postings = []
    for job in data.get("jobs", []):
        if job.get("isListed") is False:
            continue
        secondary = job.get("secondaryLocations") or []
        countries = [
            ((loc.get("address") or {}).get("postalAddress") or {}).get("addressCountry")
            for loc in [job, *secondary]
        ]
        workplace = _workplace(job.get("workplaceType")) or (
            "remote" if job.get("isRemote") else None
        )
        low, high, currency = _ashby_salary(job)
        postings.append(
            RawPosting(
                provider="ashby",
                external_id=f"{board.token}:{job['id']}",
                url=job["jobUrl"],
                title=job["title"].strip(),
                company=board.company,
                department=job.get("department") or job.get("team"),
                locations=tuple(
                    x for x in [job.get("location"), *(s.get("location") for s in secondary)] if x
                ),
                country_hints=tuple(c for c in countries if c),
                workplace=workplace,
                posted_at=parse_date(job.get("publishedAt")),
                body_html=job.get("descriptionHtml") or None,
                body_text=None if job.get("descriptionHtml") else job.get("descriptionPlain"),
                is_full_text=True,
                salary_min=to_decimal(low),
                salary_max=to_decimal(high),
                salary_currency=currency,
                licence_note=board.licence_note,
            )
        )
    return postings


async def fetch_board(client: httpx.AsyncClient, board: BoardConfig) -> list[RawPosting]:
    data = await request_json(client, "GET", board.url)
    if board.ats == "greenhouse":
        return parse_greenhouse(data, board)
    if board.ats == "lever":
        return parse_lever(data, board)
    return parse_ashby(data, board)


async def fetch_boards(
    client: httpx.AsyncClient, boards: list[BoardConfig], concurrency: int = 4
) -> tuple[list[RawPosting], dict[str, str]]:
    """Fetch every board politely. One failing board never stops the others."""
    gate = asyncio.Semaphore(concurrency)
    errors: dict[str, str] = {}

    async def one(board: BoardConfig) -> list[RawPosting]:
        async with gate:
            try:
                return await fetch_board(client, board)
            except (FetchError, KeyError, ValueError) as exc:
                errors[board.company] = str(exc)
                return []

    results = await asyncio.gather(*(one(b) for b in boards))
    return [p for batch in results for p in batch], errors
