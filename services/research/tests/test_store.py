"""Storage and the collect run, against a real migrated Postgres. HTTP is mocked."""

import copy
from typing import Any

import httpx
import pytest
import research_samples as samples
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import OperationalError

from firstweek_core.config import Settings
from firstweek_core.db.models import JobPosting, RoleAlias, RoleArchetype, Source
from firstweek_core.db.session import get_engine, session_scope
from firstweek_research.collect import run_collect
from firstweek_research.roles import load_roles
from firstweek_research.store import seed_roles

pytestmark = pytest.mark.db


@pytest.fixture(autouse=True)
def _clean_db() -> None:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError:
        pytest.skip("No database available (set DATABASE_URL and run migrations)")
    with session_scope() as session:
        session.execute(delete(JobPosting))
        session.execute(delete(Source))


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "adzuna_app_id": "id",
        "adzuna_app_key": "key",
        "firecrawl_api_key": "fc-test",
    }
    return Settings(_env_file=None, **{**base, **overrides})  # type: ignore[arg-type]


def _board_copy(data: dict[str, Any], token: str) -> dict[str, Any]:
    """Each company board gets its own URLs, but the same posting text."""
    data = copy.deepcopy(data)
    for job in data["jobs"]:
        job["absolute_url"] = job["absolute_url"].replace("/acme/", f"/{token}/")
    return data


def _transport(greenhouse: dict[str, Any] | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host == "boards-api.greenhouse.io":
            token = request.url.path.split("/")[3]
            return httpx.Response(200, json=_board_copy(greenhouse or samples.GREENHOUSE, token))
        if host == "api.lever.co":
            return httpx.Response(200, json=samples.LEVER)
        if host == "api.ashbyhq.com":
            return httpx.Response(200, json=samples.ASHBY)
        if host == "api.adzuna.com":
            return httpx.Response(200, json=samples.ADZUNA_PAGE)
        if host == "api.firecrawl.dev":
            return httpx.Response(200, json=samples.FIRECRAWL_SEARCH)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_seed_roles_is_idempotent() -> None:
    with session_scope() as session:
        first = seed_roles(session, load_roles())
        second = seed_roles(session, load_roles())
        assert first == second
        count = session.scalar(select(func.count()).select_from(RoleArchetype))
        assert count is not None and count >= 3
        alias = session.scalar(
            select(RoleAlias).where(RoleAlias.normalized_alias == "llm engineer")
        )
        assert alias is not None and alias.archetype_id == first["genai-engineer"]


async def test_collect_stores_filters_and_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("firstweek_research.collect.asyncio.sleep", _no_sleep)
    first = await run_collect("genai-engineer", _settings(), transport=_transport())

    # Every board in the list answers with the same sample, so each board adds its own copy.
    boards = first.stats("greenhouse")
    assert boards.fetched > boards.kept > 0  # the Barcelona Android role is filtered out
    assert first.stats("adzuna").new == 2  # two snippets, found again by every alias
    assert first.stats("web").new == 2  # LinkedIn and the cookie wall are dropped
    assert first.errors == {}

    with session_scope() as session:
        rows = session.scalars(select(JobPosting)).all()
        assert {r.country for r in rows} == {"GB"}
        snippet = next(r for r in rows if r.provider == "adzuna" and r.external_id == "5001")
        assert snippet.is_full_text is False
        gh = next(r for r in rows if r.provider == "greenhouse")
        assert "Benefits" not in gh.text and "RAG" in gh.text
        source = session.get(Source, gh.source_id)
        assert source is not None and "Gym" in source.content  # full text keeps everything

    # The same job from many identical boards collapses to one unique job.
    assert first.duplicates > 0

    second = await run_collect("genai-engineer", _settings(), transport=_transport())
    assert second.stats("greenhouse").new == 0
    assert second.stats("greenhouse").unchanged == boards.kept


async def test_changed_posting_is_updated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("firstweek_research.collect.asyncio.sleep", _no_sleep)
    await run_collect(
        "genai-engineer", _settings(), use_adzuna=False, use_web=False, transport=_transport()
    )
    changed = {
        **samples.GREENHOUSE,
        "jobs": [
            {
                **samples.GREENHOUSE["jobs"][0],
                "content": "&lt;p&gt;Now also LangGraph agents and evals.&lt;/p&gt;" * 3,
            }
        ],
    }
    summary = await run_collect(
        "genai-engineer",
        _settings(),
        use_adzuna=False,
        use_web=False,
        transport=_transport(changed),
    )
    assert summary.stats("greenhouse").updated > 0
    with session_scope() as session:
        texts = session.scalars(select(JobPosting.text).where(JobPosting.provider == "greenhouse"))
        assert any("LangGraph" in t for t in texts)


async def test_missing_keys_skip_sources_with_a_reason() -> None:
    summary = await run_collect(
        "genai-engineer",
        _settings(adzuna_app_id=None, adzuna_app_key=None, firecrawl_api_key=None),
        transport=_transport(),
    )
    assert "ADZUNA_APP_ID" in summary.skipped["adzuna"]
    assert "FIRECRAWL_API_KEY" in summary.skipped["web"]
    assert summary.stats("greenhouse").new > 0


async def _no_sleep(_: float) -> None:
    return None


async def test_new_cleaning_rules_refresh_stored_role_text() -> None:
    settings = _settings()
    await run_collect(
        "genai-engineer", settings, use_adzuna=False, use_web=False, transport=_transport()
    )
    with session_scope() as session:
        session.execute(
            update(JobPosting).where(JobPosting.provider == "greenhouse").values(text="stale")
        )
    summary = await run_collect(
        "genai-engineer", settings, use_adzuna=False, use_web=False, transport=_transport()
    )
    assert summary.stats("greenhouse").updated > 0  # source unchanged, role text refreshed
    with session_scope() as session:
        texts = set(
            session.scalars(select(JobPosting.text).where(JobPosting.provider == "greenhouse"))
        )
        assert "stale" not in texts
