"""Collection run for one role: fetch, filter, clean, store, de-duplicate.

M1's Temporal workflow will call these same steps as activities; for now they run as a
command so collection can be tried and inspected on its own.
"""

import asyncio
from collections import Counter
from dataclasses import dataclass, field

import httpx

from firstweek_core.config import Settings
from firstweek_core.db.session import session_scope
from firstweek_research.clean import clean_posting
from firstweek_research.locations import in_country
from firstweek_research.roles import RoleDefinition, load_roles
from firstweek_research.sources.adzuna import AdzunaCredentials, search_adzuna
from firstweek_research.sources.base import FetchError, RawPosting, WebDocument, make_client
from firstweek_research.sources.boards import fetch_boards, load_boards
from firstweek_research.sources.web import search_web
from firstweek_research.store import (
    PreparedPosting,
    apply_dedup,
    seed_roles,
    upsert_posting,
    upsert_web_document,
)

MIN_ROLE_TEXT = 80  # characters; shorter means the posting body was empty or all boilerplate


@dataclass
class ProviderStats:
    fetched: int = 0
    kept: int = 0
    new: int = 0
    updated: int = 0
    unchanged: int = 0

    def record(self, status: str) -> None:
        setattr(self, status, getattr(self, status) + 1)


@dataclass
class CollectSummary:
    role: str
    country: str
    providers: dict[str, ProviderStats] = field(default_factory=dict)
    skipped: dict[str, str] = field(default_factory=dict)  # source -> reason
    errors: dict[str, str] = field(default_factory=dict)
    duplicate_groups: int = 0
    duplicates: int = 0
    top_companies: list[tuple[str, int]] = field(default_factory=list)

    def stats(self, provider: str) -> ProviderStats:
        return self.providers.setdefault(provider, ProviderStats())


def prepare(
    raw: RawPosting, role: RoleDefinition, country: str, *, check_title: bool = True
) -> PreparedPosting | None:
    """Keep postings in the country whose title could be the role and whose body has content."""
    if not in_country(raw.locations, raw.country_hints, country):
        return None
    if check_title and not role.title_matches(raw.title):
        return None
    clean = clean_posting(raw.body_html, raw.body_text)
    min_chars = MIN_ROLE_TEXT if raw.is_full_text else 20
    if len(clean.role_text) < min_chars:
        return None
    return PreparedPosting(raw=raw, clean=clean, country=country)


async def gather_postings(
    client: httpx.AsyncClient,
    role: RoleDefinition,
    country: str,
    settings: Settings,
    summary: CollectSummary,
    *,
    use_boards: bool,
    use_adzuna: bool,
    adzuna_pages: int,
) -> list[PreparedPosting]:
    prepared: list[PreparedPosting] = []
    if use_boards:
        raws, errors = await fetch_boards(client, load_boards())
        summary.errors.update({f"board:{k}": v for k, v in errors.items()})
        for raw in raws:
            summary.stats(raw.provider).fetched += 1
            if item := prepare(raw, role, country):
                summary.stats(raw.provider).kept += 1
                prepared.append(item)
    if use_adzuna:
        if not (settings.adzuna_app_id and settings.adzuna_app_key):
            summary.skipped["adzuna"] = "ADZUNA_APP_ID / ADZUNA_APP_KEY not set in .env"
        else:
            creds = AdzunaCredentials(
                settings.adzuna_app_id, settings.adzuna_app_key.get_secret_value()
            )
            for alias in dict.fromkeys([role.name, *role.aliases]):
                try:
                    raws = await search_adzuna(
                        client, creds, alias, country=country.lower(), max_pages=adzuna_pages
                    )
                except FetchError as exc:
                    summary.errors[f"adzuna:{alias}"] = str(exc)
                    continue
                for raw in raws:
                    summary.stats("adzuna").fetched += 1
                    # Adzuna already matched the title words; the posting text is a snippet.
                    if item := prepare(raw, role, country, check_title=False):
                        summary.stats("adzuna").kept += 1
                        prepared.append(item)
                await asyncio.sleep(2.5)  # stay well under Adzuna's per-minute limit
    # The same posting can be found by several aliases.
    unique = {(p.raw.provider, p.raw.external_id): p for p in prepared}
    return list(unique.values())


async def gather_web(
    client: httpx.AsyncClient, role: RoleDefinition, settings: Settings, summary: CollectSummary
) -> list[WebDocument]:
    if settings.firecrawl_api_key is None:
        summary.skipped["web"] = "FIRECRAWL_API_KEY not set in .env"
        return []
    docs: dict[str, WebDocument] = {}
    for query in role.queries():
        try:
            for doc in await search_web(
                client, settings.firecrawl_api_key.get_secret_value(), query
            ):
                docs.setdefault(doc.url, doc)
        except FetchError as exc:
            summary.errors[f"web:{query}"] = str(exc)
    summary.stats("web").fetched = len(docs)
    summary.stats("web").kept = len(docs)
    return list(docs.values())


async def run_collect(
    role_slug: str,
    settings: Settings,
    *,
    country: str = "GB",
    use_boards: bool = True,
    use_adzuna: bool = True,
    use_web: bool = True,
    adzuna_pages: int = 2,
    transport: httpx.AsyncBaseTransport | None = None,
) -> CollectSummary:
    roles = load_roles()
    role = roles[role_slug]
    summary = CollectSummary(role=role.name, country=country)

    async with make_client(transport) as client:
        postings = await gather_postings(
            client,
            role,
            country,
            settings,
            summary,
            use_boards=use_boards,
            use_adzuna=use_adzuna,
            adzuna_pages=adzuna_pages,
        )
        web_docs = await gather_web(client, role, settings, summary) if use_web else []

    with session_scope() as session:
        seed_roles(session, roles)
        for item in postings:
            summary.stats(item.raw.provider).record(upsert_posting(session, item))
        for doc in web_docs:
            summary.stats("web").record(upsert_web_document(session, doc))
        result = apply_dedup(session, country)
    summary.duplicate_groups = result.group_count
    summary.duplicates = len(result.duplicates)
    summary.top_companies = Counter(p.raw.company or "Unknown" for p in postings).most_common(8)
    return summary
