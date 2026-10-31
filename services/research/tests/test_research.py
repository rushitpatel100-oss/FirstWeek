"""A full research run (collect, classify, extract, statistics) on the test database.

HTTP and the model are both faked, so this costs nothing and needs no keys.
"""

import pytest
import research_samples as samples
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import OperationalError
from test_extract import fake_gateway

from firstweek_core.config import Settings
from firstweek_core.db.models import (
    ArchetypeVersion,
    Extraction,
    JobPosting,
    PostingRoleMatch,
    Source,
)
from firstweek_core.db.session import get_engine, session_scope
from firstweek_research.research import ResearchResult, run_research

pytestmark = pytest.mark.db


@pytest.fixture(autouse=True)
def _clean_db() -> None:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError:
        pytest.skip("No database available")
    with session_scope() as session:
        session.execute(delete(ArchetypeVersion))
        session.execute(delete(JobPosting))
        session.execute(delete(Source))


def _settings() -> Settings:
    return Settings(_env_file=None, adzuna_app_id="id", adzuna_app_key="key")


async def _run(**overrides: object) -> ResearchResult:
    kwargs: dict[str, object] = {
        "use_web": False,
        "transport": samples.mock_transport(),
        "budget_usd": 5.0,
    }
    kwargs.update(overrides)
    return await run_research("genai-engineer", _settings(), fake_gateway(), **kwargs)  # type: ignore[arg-type]


async def test_research_run_end_to_end_and_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("firstweek_research.collect.asyncio.sleep", _no_sleep)
    first = await _run()

    assert first.classified == 2  # one unique board posting per sample job that fits the title
    assert first.matched == 2 and first.extracted == 2
    assert first.failures == {}
    assert first.version == 1
    stats = first.stats
    assert stats is not None
    assert stats.sample_size == 2
    assert stats.sources == {"greenhouse": 1, "ashby": 1}
    assert stats.unverified_items_dropped == 2  # the invented Kubernetes quote, once per posting
    assert stats.demand_snippets == 2  # Adzuna titles that resolve to GenAI Engineer
    assert stats.salary == []  # fewer than three stated salaries
    top = {s.skill_id: s for s in stats.skills + stats.tools}
    assert top["python"].count == 2 and top["python"].share == 1.0
    assert top["python"].ci_low < 1.0 == top["python"].ci_high  # n=2 is very uncertain
    assert first.cost_usd > 0

    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(PostingRoleMatch)) == 2
        kubernetes = session.scalar(
            select(func.count()).select_from(Extraction).where(Extraction.raw_text == "Kubernetes")
        )
        assert kubernetes == 0  # never stored

    second = await _run(collect=True)
    assert second.classified == 0 and second.extracted == 0  # all cached
    assert second.cost_usd == 0
    assert second.version == 2
    assert second.stats is not None and second.stats.sample_size == 2


async def test_empty_sample_saves_no_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("firstweek_research.collect.asyncio.sleep", _no_sleep)
    result = await _run(use_boards=False)  # Adzuna snippets only: never in the sample
    assert result.stats is not None and result.stats.sample_size == 0
    assert result.version is None


async def test_budget_stops_paid_calls_without_crashing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("firstweek_research.collect.asyncio.sleep", _no_sleep)
    result = await _run(budget_usd=0.0001)
    assert result.classified == 0
    assert result.failures and all("Budget" in v for v in result.failures.values())


async def _no_sleep(_: float) -> None:
    return None
