"""Web evidence via Firecrawl search: engineering blogs, docs and practitioner forums.

Tier 2 (blogs, docs) says how work is actually done; tier 3 (forums) says what the
unglamorous parts are. Sites whose terms forbid scraping, job boards and course sellers are
excluded: a course seller's "what does an X do" page is written to sell a course, not to
report the work (seen 2026-10-31: Udacity's catalogue cards outranking practitioners).
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
    "careervillage.org",
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
    # Course sellers and bootcamps (ADR 0012 addendum).
    "udacity.com",
    "coursera.org",
    "udemy.com",
    "edx.org",
    "simplilearn.com",
    "edureka.co",
    "datacamp.com",
    "codecademy.com",
    "educative.io",
    "mygreatlearning.com",
    "upgrad.com",
    "scaler.com",
    "intellipaat.com",
    "knowledgehut.com",
    "careerfoundry.com",
    "springboard.com",
    "365datascience.com",
    "emeritus.org",
    # Training providers whose "day in the life" pages sell courses (ADR 0013 addendum).
    "cloudthat.com",
    "bigblue.academy",
    "aiengineeringfromscratch.com",
    # Research papers: not practitioner accounts of the work (ADR 0013 addendum).
    "arxiv.org",
]
LICENCE = (
    "Public web page fetched via Firecrawl for research. Quote briefly, attribute the "
    "publisher and link to the original."
)


def domain_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host.removeprefix("www.").removeprefix("old.")


def is_excluded(url: str) -> bool:
    domain = domain_of(url)
    return any(domain == d or domain.endswith("." + d) for d in EXCLUDED_DOMAINS)


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
        if is_excluded(url):
            continue
        domain = domain_of(url)
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
    client: httpx.AsyncClient,
    api_key: str,
    query: str,
    *,
    limit: int = 5,
    include_domains: list[str] | None = None,
) -> list[WebDocument]:
    """One search; each result is scraped to markdown. Costs ~1 Firecrawl credit per result.

    With include_domains the search is limited to those sites (Firecrawl allows either
    includeDomains or excludeDomains, not both).
    """
    domains = (
        {"includeDomains": include_domains}
        if include_domains
        else {"excludeDomains": EXCLUDED_DOMAINS}
    )
    data = await request_json(
        client,
        "POST",
        SEARCH_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "query": query,
            "limit": limit,
            "sources": [{"type": "web"}],
            **domains,
            "scrapeOptions": {"formats": [{"type": "markdown"}], "onlyMainContent": True},
        },
    )
    return parse_search(data, query)
