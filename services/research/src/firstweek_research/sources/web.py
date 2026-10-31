"""Web evidence via Firecrawl search: engineering blogs, docs and practitioner forums.

Tier 2 (blogs, docs) says how work is actually done; tier 3 (forums) says what the
unglamorous parts are. Sites whose terms forbid scraping, and job boards, are excluded.
"""

from typing import Any, Literal
from urllib.parse import urlparse

import httpx

from firstweek_research.sources.base import WebDocument, request_json

SEARCH_URL = "https://api.firecrawl.dev/v2/search"
MIN_CHARS = 500  # shorter pages are almost always navigation or cookie walls

FORUM_DOMAINS = {
    "reddit.com",
    "news.ycombinator.com",
    "stackoverflow.com",
    "stackexchange.com",
    "lobste.rs",
    "community.openai.com",
}
EXCLUDED_DOMAINS = [
    "linkedin.com",
    "glassdoor.com",
    "glassdoor.co.uk",
    "indeed.com",
    "uk.indeed.com",
    "ziprecruiter.com",
    "totaljobs.com",
    "reed.co.uk",
    "monster.com",
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "x.com",
    "twitter.com",
    "youtube.com",
]
LICENCE = (
    "Public web page fetched via Firecrawl for research. Quote briefly, attribute the "
    "publisher and link to the original."
)


def domain_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host.removeprefix("www.").removeprefix("old.")


def tier_for(domain: str) -> Literal["blog", "forum"]:
    return (
        "forum" if any(domain == d or domain.endswith("." + d) for d in FORUM_DOMAINS) else "blog"
    )


def parse_search(data: dict[str, Any], query: str) -> list[WebDocument]:
    docs = []
    for item in (data.get("data") or {}).get("web") or []:
        url = item.get("url") or (item.get("metadata") or {}).get("sourceURL")
        markdown = item.get("markdown") or ""
        if not url or len(markdown) < MIN_CHARS:
            continue
        domain = domain_of(url)
        if any(domain == d or domain.endswith("." + d) for d in EXCLUDED_DOMAINS):
            continue
        docs.append(
            WebDocument(
                url=url,
                title=item.get("title") or (item.get("metadata") or {}).get("title"),
                publisher=domain,
                markdown=markdown,
                tier=tier_for(domain),
                query=query,
                licence_note=LICENCE,
            )
        )
    return docs


async def search_web(
    client: httpx.AsyncClient, api_key: str, query: str, *, limit: int = 5
) -> list[WebDocument]:
    """One search; each result is scraped to markdown. Costs ~1 Firecrawl credit per result."""
    data = await request_json(
        client,
        "POST",
        SEARCH_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "query": query,
            "limit": limit,
            "sources": [{"type": "web"}],
            "excludeDomains": EXCLUDED_DOMAINS,
            "scrapeOptions": {"formats": [{"type": "markdown"}], "onlyMainContent": True},
        },
    )
    return parse_search(data, query)
