import json
from datetime import date
from decimal import Decimal

import httpx
import pytest
import research_samples as samples

from firstweek_research.sources.adzuna import AdzunaCredentials, search_adzuna
from firstweek_research.sources.base import FetchError, make_client, request_json
from firstweek_research.sources.boards import (
    BoardConfig,
    fetch_boards,
    load_boards,
    parse_ashby,
    parse_greenhouse,
    parse_lever,
)
from firstweek_research.sources.web import is_excluded, search_web

GH = BoardConfig(company="Acme AI", ats="greenhouse", token="acme")
LV = BoardConfig(company="Acme AI", ats="lever", token="acme")
AB = BoardConfig(company="Acme AI", ats="ashby", token="acme")


def test_board_list_loads_with_unique_tokens() -> None:
    boards = load_boards()
    assert len(boards) >= 80
    assert len({(b.ats, b.token) for b in boards}) == len(boards)
    assert len({b.company for b in boards}) == len(boards)


def test_parse_greenhouse_unescapes_html_and_keeps_metadata() -> None:
    first, second = parse_greenhouse(samples.GREENHOUSE, GH)
    assert first.external_id == "acme:101"
    assert first.title == "Senior GenAI Engineer"
    assert first.body_html is not None and first.body_html.startswith("<h2>About the role</h2>")
    assert first.locations == ("London, UK", "London")
    assert first.department == "Applied AI"
    assert first.posted_at == date(2026, 10, 1)
    assert first.is_full_text
    assert second.posted_at == date(2026, 10, 20)  # falls back to updated_at


def test_parse_lever_joins_description_lists_and_additional() -> None:
    (job,) = parse_lever(samples.LEVER, LV)
    assert job.country_hints == ("GB",)
    assert job.locations == ("London", "Manchester")
    assert job.workplace == "hybrid"
    assert job.body_html is not None
    assert "<h3>What you'll do</h3>" in job.body_html
    assert "equal opportunity" in job.body_html


def test_parse_ashby_skips_unlisted_and_reads_salary() -> None:
    (job,) = parse_ashby(samples.ASHBY, AB)
    assert job.country_hints == ("United Kingdom", "United Kingdom")
    assert job.workplace == "onsite"
    assert (job.salary_min, job.salary_max, job.salary_currency) == (
        Decimal("90000"),
        Decimal("120000"),
        "GBP",
    )
    assert job.locations == ("London", "Remote (UK)")


async def test_fetch_boards_survives_one_failing_board() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "greenhouse" in request.url.host:
            return httpx.Response(200, json=samples.GREENHOUSE)
        return httpx.Response(404)

    async with make_client(httpx.MockTransport(handler)) as client:
        postings, errors = await fetch_boards(client, [GH, LV])
    assert len(postings) == 2
    assert "Acme AI" in errors and "404" in errors["Acme AI"]


async def test_request_json_retries_rate_limits() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429) if calls["n"] < 3 else httpx.Response(200, json={"ok": True})

    async with make_client(httpx.MockTransport(handler)) as client:
        assert await request_json(client, "GET", "https://x.test", backoff_s=0) == {"ok": True}
        calls["n"] = -10
        with pytest.raises(FetchError, match="429"):
            await request_json(client, "GET", "https://x.test", backoff_s=0)


async def test_adzuna_marks_snippets_and_drops_predicted_salaries() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=samples.ADZUNA_PAGE)

    async with make_client(httpx.MockTransport(handler)) as client:
        postings = await search_adzuna(
            client, AdzunaCredentials("id", "key"), "GenAI Engineer", max_pages=3
        )
    assert len(seen) == 1  # fewer than 50 results means the last page
    assert seen[0].url.params["title_only"] == "GenAI Engineer"
    assert seen[0].url.path == "/v1/api/jobs/gb/search/1"
    stated, predicted = postings
    assert not stated.is_full_text and stated.body_text
    assert (stated.salary_min, stated.salary_currency) == (Decimal("70000"), "GBP")
    assert predicted.salary_min is None and predicted.salary_currency is None
    assert stated.country_hints == ("UK",)


async def test_web_search_tiers_results_and_filters_junk() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.headers["Authorization"] == "Bearer fc-test"
        assert "linkedin.com" in body["excludeDomains"]
        return httpx.Response(200, json=samples.FIRECRAWL_SEARCH)

    async with make_client(httpx.MockTransport(handler)) as client:
        docs = await search_web(client, "fc-test", "genai engineer day in the life")
    assert [(d.publisher, d.tier) for d in docs] == [
        ("engineering.example.com", "blog"),
        ("reddit.com", "forum"),
    ]


def test_course_sellers_and_job_boards_are_not_evidence() -> None:
    assert is_excluded("https://www.udacity.com/topic/what-is-an-agentic-ai-engineer")
    assert is_excluded("https://blog.coursera.org/ai-engineer")  # subdomains too
    assert is_excluded("https://uk.linkedin.com/jobs/view/1")
    assert not is_excluded("https://dev.to/marianocodes/lessons-from-building-ai-agents")
    assert not is_excluded("https://notudacity.com/post")  # a suffix match, not a substring
