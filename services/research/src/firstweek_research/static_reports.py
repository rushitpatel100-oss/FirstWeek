"""Researched Role Reality Reports kept in the repository, so a role has a published report
with no model call and no API key (ADR 0027).

Each golden role has two files in `data/static_reports/`:

- `<slug>.sample.json`: the job postings behind the numbers (employer, title, link, date) and
  the taxonomy skills named in each one, found by `keyword_skills`. The shares in the report
  are counted from this file by code, and a test recounts them.
- `<slug>.report.json`: the report itself. Every claim quotes its sources word for word.
  `make check-reports` fetches every source again and confirms each quote is still there.

`make seed-reports` stores them as published reports, which the API and web app then serve
like any other.
"""

import asyncio
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from importlib import resources
from typing import Literal
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import func, select

from firstweek_core.contracts import ArchetypeStats, Citation, Claim, RoleRealityReport
from firstweek_core.contracts.research import TIER_WEIGHTS
from firstweek_core.db.models import ArchetypeVersion, ReportClaim, RoleArchetype, RoleReport
from firstweek_core.db.session import session_scope
from firstweek_research.clean import clean_posting, html_to_text
from firstweek_research.roles import load_roles
from firstweek_research.sources.boards import BoardConfig, fetch_board, load_boards
from firstweek_research.stats import _skill_stats
from firstweek_research.store import seed_roles
from firstweek_research.verify import STRONG_SOURCES, recency

STATIC_ROLES = ("genai-engineer", "agentic-ai-engineer", "ai-software-engineer")
METHOD = "researched"
CLASSIFIER = "hand-labelled against the role definition"
EXTRACTOR = "keyword-skills.v1"
SECTIONS = ("summary", "responsibilities", "day_to_day", "typical_week", "pain_points")
ATS_HOSTS = {
    "job-boards.greenhouse.io",
    "job-boards.eu.greenhouse.io",
    "boards.greenhouse.io",
    "jobs.lever.co",
    "jobs.eu.lever.co",
    "jobs.ashbyhq.com",
}


class SamplePosting(BaseModel):
    company: str
    board: str = Field(description="Token of the job board it came from (data/sources)")
    title: str
    url: HttpUrl
    posted: date | None
    skills: dict[str, str] = Field(description="Skill id -> the words that named it")


class StaticSample(BaseModel):
    role: str
    country: str = Field(min_length=2, max_length=2)
    collected: date
    how_chosen: str
    postings: list[SamplePosting] = Field(min_length=1)


def _folder() -> resources.abc.Traversable:
    return resources.files("firstweek_research") / "data" / "static_reports"


def load_sample(slug: str) -> StaticSample:
    return StaticSample.model_validate_json((_folder() / f"{slug}.sample.json").read_text("utf-8"))


def load_report(slug: str) -> RoleRealityReport:
    text = (_folder() / f"{slug}.report.json").read_text("utf-8")
    return RoleRealityReport.model_validate_json(text)


# ------------------------------------------------------------------ numbers, by code


def stats_from_sample(sample: StaticSample) -> ArchetypeStats:
    """The same statistics the pipeline stores, counted from the hand-checked sample."""
    n = len(sample.postings)
    counts: Counter[str] = Counter(s for p in sample.postings for s in p.skills)
    dates = [p.posted for p in sample.postings if p.posted is not None]
    return ArchetypeStats(
        role=sample.role,
        country=sample.country,
        sample_size=n,
        employers=len({p.company for p in sample.postings}),
        date_range=(min(dates), max(dates)) if dates else (sample.collected, sample.collected),
        sources={"job boards": n},
        skills=_skill_stats(counts, n, "skill"),
        tools=_skill_stats(counts, n, "tool"),
        seniority={},
        salary=[],
        demand_snippets=0,
        unverified_items_dropped=0,
        unmapped_terms=0,
        classifier_version=CLASSIFIER,
        extractor_version=EXTRACTOR,
    )


def publisher(url: str) -> str:
    """Who published a source: the employer for a job-board posting, else the site."""
    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    if host in ATS_HOSTS:
        return parsed.path.strip("/").split("/")[0].lower()
    return host


def confidence(citations: Sequence[Citation], today: date) -> float:
    """The pipeline's formula (verify.score) with every cited source judged as supporting:
    independent sources add up, by tier and age, until three strong ones make it certain."""
    best: dict[str, float] = {}
    for c in citations:
        key = f"{c.tier}:{publisher(str(c.source_url))}"
        best[key] = max(best.get(key, 0.0), TIER_WEIGHTS[c.tier] * recency(c.published, today))
    return round(min(1.0, sum(best.values()) / STRONG_SOURCES), 3)


# ------------------------------------------------------------------ quotes, by code

_QUOTES = str.maketrans(
    {
        "\u2019": "'",  # right single quote
        "\u2018": "'",  # left single quote
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",  # en dash
        "\u2014": "-",  # em dash
        "\u00a0": " ",  # no-break space
    }
)


def normalise(text: str) -> str:
    """Compare quotes the way a reader would: curly quotes, dashes and spacing don't count."""
    return re.sub(r"\s+", " ", text.translate(_QUOTES)).strip()


def quote_found(quote: str, page_text: str) -> bool:
    return normalise(quote) in normalise(page_text)


@dataclass(frozen=True)
class QuoteCheck:
    section: str
    url: str
    quote: str
    status: Literal["found", "missing", "closed", "unreachable"]


def citations(report: RoleRealityReport) -> list[tuple[str, Citation]]:
    found: list[tuple[str, Citation]] = []
    for section in SECTIONS:
        claims: list[Claim] = getattr(report, section)
        found.extend((section, c) for claim in claims for c in claim.citations)
    return found


async def _posting_texts(
    client: httpx.AsyncClient, sample: StaticSample, urls: set[str]
) -> dict[str, str]:
    """The current text of each cited posting that is still open, from its company's board."""
    wanted = {p.board for p in sample.postings if str(p.url) in urls}
    boards: list[BoardConfig] = [b for b in load_boards() if b.token in wanted]
    texts: dict[str, str] = {}
    for board in boards:
        try:
            postings = await fetch_board(client, board)
        except httpx.HTTPError:
            continue
        for raw in postings:
            if raw.url in urls:
                texts[raw.url] = clean_posting(raw.body_html, raw.body_text).role_text
    return texts


async def check_quotes(slug: str, client: httpx.AsyncClient) -> list[QuoteCheck]:
    """Fetches every source again and looks for each quote. A posting that has closed since
    is reported as closed, not as wrong."""
    report, sample = load_report(slug), load_sample(slug)
    cited = citations(report)
    post_urls = {str(c.source_url) for _, c in cited if c.tier == "posting"}
    posts = await _posting_texts(client, sample, post_urls)
    pages: dict[str, str | None] = {}
    results = []
    for section, c in cited:
        url = str(c.source_url)
        if c.tier == "posting":
            text = posts.get(url)
            status = _status(text, c.quote, gone="closed")
        else:
            if url not in pages:
                try:
                    response = await client.get(url, follow_redirects=True)
                    response.raise_for_status()
                    pages[url] = html_to_text(response.text)
                except httpx.HTTPError:
                    pages[url] = None
            status = _status(pages[url], c.quote, gone="unreachable")
        results.append(QuoteCheck(section, url, c.quote, status))
    return results


def _status(
    text: str | None, quote: str, gone: Literal["closed", "unreachable"]
) -> Literal["found", "missing", "closed", "unreachable"]:
    if text is None:
        return gone
    return "found" if quote_found(quote, text) else "missing"


def check_all(slugs: Iterable[str] = STATIC_ROLES) -> dict[str, list[QuoteCheck]]:
    async def run() -> dict[str, list[QuoteCheck]]:
        headers = {"User-Agent": "FirstWeek research (portfolio project)"}
        async with httpx.AsyncClient(timeout=30, headers=headers) as client:
            return {slug: await check_quotes(slug, client) for slug in slugs}

    return asyncio.run(run())


# ------------------------------------------------------------------ storing


def seed(slugs: Iterable[str] = STATIC_ROLES) -> dict[str, str]:
    """Stores each role's researched report as published, with its statistics as a new
    version. Running it again changes nothing: an identical published report is kept."""
    roles = load_roles()
    outcome: dict[str, str] = {}
    now = datetime.now(UTC)
    with session_scope() as session:
        seed_roles(session, {slug: roles[slug] for slug in slugs})
        for slug in slugs:
            sample, report = load_sample(slug), load_report(slug)
            archetype = session.scalars(
                select(RoleArchetype).where(RoleArchetype.slug == slug)
            ).one()
            existing = session.scalars(
                select(RoleReport)
                .join(ArchetypeVersion, ArchetypeVersion.id == RoleReport.archetype_version_id)
                .where(
                    ArchetypeVersion.archetype_id == archetype.id,
                    RoleReport.status == "published",
                )
            ).all()
            if any(_same(row.report, report) for row in existing):
                outcome[slug] = "already stored"
                continue
            stats = stats_from_sample(sample)
            latest = session.scalar(
                select(func.max(ArchetypeVersion.version)).where(
                    ArchetypeVersion.archetype_id == archetype.id
                )
            )
            assert stats.date_range is not None
            version = ArchetypeVersion(
                archetype_id=archetype.id,
                version=(latest or 0) + 1,
                country=stats.country,
                date_from=stats.date_range[0],
                date_to=stats.date_range[1],
                sample_size=stats.sample_size,
                stats=stats.model_dump(mode="json"),
                status="published",
                reviewed_at=now,
            )
            session.add(version)
            session.flush()
            stored = _with_stats_version(report, version.version)
            row = RoleReport(
                archetype_version_id=version.id,
                report=stored.model_dump(mode="json"),
                status="published",
                reviewed_at=now,
                published_at=now,
            )
            session.add(row)
            session.flush()
            for section in SECTIONS:
                for claim in getattr(stored, section):
                    session.add(
                        ReportClaim(
                            report_id=row.id,
                            section=section,
                            text=claim.text,
                            confidence=claim.confidence,
                            verification=claim.verification,
                            passage_ids=[],
                            review="accepted",
                            review_note="researched report: quotes checked by code",
                        )
                    )
            outcome[slug] = f"stored as statistics version {version.version}"
    return outcome


def _with_stats_version(report: RoleRealityReport, version: int) -> RoleRealityReport:
    assert report.provenance is not None
    provenance = report.provenance.model_copy(update={"stats_version": version})
    return report.model_copy(update={"provenance": provenance})


def _same(stored: object, report: RoleRealityReport) -> bool:
    """True when a stored report is this researched report (whatever version it was given)."""
    if not isinstance(stored, dict) or (stored.get("provenance") or {}).get("method") != METHOD:
        return False
    found = RoleRealityReport.model_validate(stored)
    return _with_stats_version(found, 1) == _with_stats_version(report, 1)
