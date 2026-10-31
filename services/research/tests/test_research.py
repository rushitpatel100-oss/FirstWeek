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
from firstweek_research.research import ResearchResult, match_decisions, run_research

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
    messages: list[str] = []
    first = await _run(progress=messages.append)

    assert any(m.startswith("Fetching") for m in messages)
    assert "  2/2 classified" in messages and "  2/2 extracted" in messages
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


async def test_interrupted_run_keeps_what_it_paid_for(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("firstweek_research.collect.asyncio.sleep", _no_sleep)
    gateway = fake_gateway()
    real = gateway.completion_fn
    assert real is not None
    calls = 0

    async def drops_the_second_call(**kwargs: object) -> object:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("connection lost")
        return await real(**kwargs)

    gateway.completion_fn = drops_the_second_call
    with pytest.raises(RuntimeError):
        await run_research(
            "genai-engineer",
            _settings(),
            gateway,
            use_web=False,
            transport=samples.mock_transport(),
        )
    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(PostingRoleMatch)) == 1

    resumed = await _run(collect=False)
    assert resumed.classified == 1  # only the one that was lost


async def test_changing_a_definition_re_checks_every_posting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("firstweek_research.collect.asyncio.sleep", _no_sleep)
    first = await _run()
    assert first.classified == 2

    from firstweek_research.roles import RoleDefinition

    monkeypatch.setattr(RoleDefinition, "definition_hash", property(lambda _: "edited00edited00"))
    second = await _run(collect=False)
    assert second.classified == 2  # decisions against the old wording are not reused
    assert second.extracted == 0  # extraction does not depend on the definition
    assert second.stats is not None and second.stats.definition_hash == "edited00edited00"
    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(PostingRoleMatch)) == 4


async def test_match_review_lists_decisions_and_unclassified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("firstweek_research.collect.asyncio.sleep", _no_sleep)
    await _run(budget_usd=0.0001)  # every classification fails on budget
    pending = match_decisions("genai-engineer")
    assert len(pending) == 2
    assert all(r.is_match is None and not r.counted for r in pending)

    await _run(collect=False)
    decided = match_decisions("genai-engineer")
    assert [r.counted for r in decided] == [True, True]
    assert all(r.reason and r.url.startswith("https://") for r in decided)


async def _no_sleep(_: float) -> None:
    return None
