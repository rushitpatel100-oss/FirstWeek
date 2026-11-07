"""The researched reports kept in the repository (ADR 0027): every number recounts from the
sample, every confidence recomputes from the citations, and seeding publishes them."""

from datetime import date

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import OperationalError

from firstweek_core.contracts import Citation, Claim
from firstweek_core.contracts.research import Tier
from firstweek_core.db.models import ArchetypeVersion, ReportClaim, RoleArchetype, RoleReport
from firstweek_core.db.session import get_engine, session_scope
from firstweek_research import static_reports as sr
from firstweek_research.keyword_skills import find_skills
from firstweek_research.report import asked_for
from firstweek_research.roles import load_roles
from firstweek_research.taxonomy import load_taxonomy

ROLES = sr.STATIC_ROLES


@pytest.mark.parametrize("slug", ROLES)
def test_shares_are_recounted_from_the_sample(slug: str) -> None:
    report, sample = sr.load_report(slug), sr.load_sample(slug)
    stats = sr.stats_from_sample(sample)
    assert report.sample_size == len(sample.postings) == stats.sample_size
    assert report.asked_for == asked_for(stats)
    assert report.date_range == stats.date_range
    assert len({str(p.url) for p in sample.postings}) == len(sample.postings)


@pytest.mark.parametrize("slug", ROLES)
def test_sample_uses_known_skills_and_roles(slug: str) -> None:
    sample = sr.load_sample(slug)
    taxonomy = load_taxonomy()
    assert sample.role == slug and slug in load_roles()
    for posting in sample.postings:
        assert set(posting.skills) <= set(taxonomy.entries)
        assert all(words for words in posting.skills.values())


@pytest.mark.parametrize("slug", ROLES)
def test_confidence_recomputes_from_citations(slug: str) -> None:
    report, sample = sr.load_report(slug), sr.load_sample(slug)
    for _, claim in _claims(slug):
        assert claim.confidence == sr.confidence(claim.citations, sample.collected)
        assert claim.verification == "supported"
        assert any(c.tier != "forum" for c in claim.citations)
    assert report.provenance is not None
    assert report.provenance.method == "researched"
    assert report.provenance.cost_usd == 0.0


@pytest.mark.parametrize("slug", ROLES)
def test_posting_citations_point_into_the_sample(slug: str) -> None:
    sample = sr.load_sample(slug)
    posted = {str(p.url): p.posted for p in sample.postings}
    for _, c in sr.citations(sr.load_report(slug)):
        if c.tier == "posting":
            assert str(c.source_url) in posted
            assert c.published == posted[str(c.source_url)]


@pytest.mark.parametrize("slug", ROLES)
def test_every_section_has_claims(slug: str) -> None:
    report = sr.load_report(slug)
    for section in sr.SECTIONS:
        if section != "typical_week":
            assert getattr(report, section), section


def _claims(slug: str) -> list[tuple[str, Claim]]:
    report = sr.load_report(slug)
    return [(s, c) for s in sr.SECTIONS for c in getattr(report, s)]


# ---------------------------------------------------------------- the pieces


def test_quotes_match_despite_curly_quotes_and_spacing() -> None:
    page = "You\u2019ll own  the whole stack \u2014\nfrom prompts to evals."
    assert sr.quote_found("You'll own the whole stack - from prompts to evals.", page)
    assert not sr.quote_found("You'll own the stack", page)


def test_publisher_is_the_employer_on_job_boards() -> None:
    assert sr.publisher("https://jobs.ashbyhq.com/motorway/85582e6d") == "motorway"
    assert sr.publisher("https://job-boards.greenhouse.io/addepar1/jobs/889") == "addepar1"
    assert sr.publisher("https://www.hamel.dev/blog/posts/evals-faq/") == "hamel.dev"


def _cite(url: str, tier: Tier, published: date | None) -> Citation:
    return Citation.model_validate(
        {"source_url": url, "tier": tier, "quote": "words", "published": published}
    )


def test_confidence_follows_the_pipeline_formula() -> None:
    today = date(2026, 11, 7)
    recent = date(2026, 6, 1)
    three_employers = [
        _cite(f"https://jobs.ashbyhq.com/{c}/1", "posting", recent) for c in ("a", "b", "c")
    ]
    assert sr.confidence(three_employers, today) == 1.0
    same_employer = [_cite(f"https://jobs.ashbyhq.com/a/{i}", "posting", recent) for i in (1, 2)]
    assert sr.confidence(same_employer, today) == round(1 / 3, 3)
    two_blogs = [_cite("https://x.dev/a", "blog", recent), _cite("https://y.dev/b", "blog", None)]
    assert sr.confidence(two_blogs, today) == round((0.8 + 0.8 * 0.7) / 3, 3)


def test_keyword_skills_reads_names_not_lookalikes() -> None:
    text = (
        "You'll use Python, Go and TypeScript to build agentic workflows with RAG and LangGraph. "
        "Send your CV. We value collaboration and go-to-market speed. JavaScript is a plus."
    )
    found = {m.skill_id: m.words for m in find_skills(text, "Acme")}
    assert found["go"] == "Go"
    assert found["ai-agents"] == "agentic workflows"
    assert {"python", "typescript", "rag", "langgraph", "javascript"} <= set(found)
    assert "java" not in found  # 'JavaScript' is not Java
    assert "computer-vision" not in found  # 'CV' is a résumé here
    assert "cross-functional-collaboration" not in found


def test_keyword_skills_ignores_a_vendors_own_name() -> None:
    text = "At OpenAI you will build with the OpenAI API and Claude."
    assert "openai-api" not in {m.skill_id for m in find_skills(text, "OpenAI")}
    assert "openai-api" in {m.skill_id for m in find_skills(text, "Monzo")}


# ---------------------------------------------------------------- storing (test database)


@pytest.fixture
def _clean_db() -> None:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError:
        pytest.skip("No database available")
    with session_scope() as session:
        session.execute(delete(RoleReport))
        session.execute(delete(ArchetypeVersion))
        session.execute(delete(RoleArchetype))


@pytest.mark.usefixtures("_clean_db")
def test_seed_publishes_each_report_once() -> None:
    first = sr.seed()
    assert all(o.startswith("stored as statistics version 1") for o in first.values())
    assert set(sr.seed().values()) == {"already stored"}
    with session_scope() as session:
        rows = session.scalars(select(RoleReport)).all()
        assert len(rows) == 3 and {r.status for r in rows} == {"published"}
        assert all(r.published_at is not None for r in rows)
        versions = session.scalars(select(ArchetypeVersion)).all()
        assert {v.status for v in versions} == {"published"}
        claims = session.scalar(select(func.count()).select_from(ReportClaim))
    expected = sum(len(_claims(slug)) for slug in ROLES)
    assert claims == expected


@pytest.mark.usefixtures("_clean_db")
def test_seed_adds_a_version_after_pipeline_versions() -> None:
    sr.seed(["genai-engineer"])
    with session_scope() as session:
        session.execute(delete(RoleReport))  # as if only pipeline statistics existed
    assert sr.seed(["genai-engineer"]) == {"genai-engineer": "stored as statistics version 2"}
    with session_scope() as session:
        stored = session.scalars(select(RoleReport)).one()
        assert stored.report["provenance"]["stats_version"] == 2
