"""The report writer: wording from statistics, the claim checks, and a full draft written by
a fake model from real retrieval over a test database."""

import json
import re
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import delete
from test_passages import add_page, add_posting, bag_of_words, db_fixture
from test_retrieve import _decide

from firstweek_core.config import Settings
from firstweek_core.contracts import (
    ArchetypeStats,
    DraftCitation,
    DraftClaim,
    SectionDraft,
    SkillStat,
)
from firstweek_core.db.models import ArchetypeVersion
from firstweek_core.db.session import session_scope
from firstweek_core.llm import BudgetRegistry, LLMGateway
from firstweek_core.llm.tracing import NoopTracer
from firstweek_research import report as rp
from firstweek_research.passages import index_evidence
from firstweek_research.retrieve import Hit
from firstweek_research.roles import load_roles
from firstweek_research.stats import save_version
from firstweek_research.store import seed_roles

__all__ = ["db_fixture"]  # registers the _db fixture here

ROLE = "genai-engineer"


def stat(label: str, share: float, n: int = 20) -> SkillStat:
    return SkillStat(
        skill_id=label.lower(),
        label=label,
        count=round(share * n),
        share=share,
        ci_low=max(0.0, share - 0.2),
        ci_high=min(1.0, share + 0.2),
        n=n,
    )


def stats(skills: list[SkillStat]) -> ArchetypeStats:
    return ArchetypeStats(
        role="GenAI Engineer",
        country="GB",
        sample_size=20,
        employers=14,
        date_range=(date(2026, 5, 4), date(2026, 10, 28)),
        sources={"greenhouse": 20},
        skills=skills,
        tools=[],
        seniority={"senior": 12, "mid": 8},
        salary=[],
        demand_snippets=0,
        unverified_items_dropped=0,
        unmapped_terms=0,
        classifier_version="classify-role.v1",
        extractor_version="extract-posting.v1",
    )


# ---------------------------------------------------------------------- statistics


@pytest.mark.parametrize(
    ("share", "words"),
    [
        (0.60, "Most roles ask for"),
        (0.59, "Many roles ask for"),
        (0.30, "Many roles ask for"),
        (0.29, "Some roles ask for"),
        (0.10, "Some roles ask for"),
        (0.09, None),
    ],
)
def test_frequency_words_follow_the_plan_bands(share: float, words: str | None) -> None:
    assert rp.band(share) == words


def test_the_headline_states_the_sample_and_the_bands() -> None:
    s = stats([stat("Python", 0.8), stat("RAG", 0.65), stat("Docker", 0.35), stat("Go", 0.05)])
    items = rp.asked_for(s)
    assert [i.label for i in items] == ["Python", "RAG", "Docker"]  # under 10% is left out
    assert rp.headline(s, items) == (
        "Based on 20 GB job postings from 14 employers, all open in the last six months "
        "(posted May 2026 to Oct 2026). "
        "Most roles ask for Python (80%) and RAG (65%). Many roles ask for Docker (35%)."
    )


def test_the_skill_list_shows_the_top_in_full_and_folds_the_rest_by_band() -> None:
    shares = [0.9, 0.8, 0.7, 0.6, 0.55, 0.5, 0.45, 0.42, 0.4, 0.38, 0.36, 0.35, 0.34, 0.33]
    items = [stat(f"S{i:02}", share) for i, share in enumerate(shares)]
    items += [stat(f"T{i}", 0.31) for i in range(3)]  # the 15th to 17th tie: all shown
    items += [stat("RAG", 0.30), stat("AWS", 0.25), stat("Go", 0.15)]
    lines = rp.asked_for_lines(items)
    assert len(lines) == 17 + 2
    assert lines[0] == "- Most roles ask for S00: 90% of 20 postings (95% interval 70% to 100%)"
    assert lines[16].startswith("- Many roles ask for T2: 31%")
    assert lines[17:] == [
        "- Many roles also ask for: RAG (30%)",
        "- Some roles also ask for: AWS (25%), Go (15%)",
    ]
    assert len(rp.asked_for_lines(items[:4])) == 4  # a short list has nothing to fold


# ---------------------------------------------------------------------- checks


def hit(n: int, text: str, tier: str = "blog", source: int | None = None) -> Hit:
    import uuid

    return Hit(
        passage_id=uuid.UUID(int=n),
        source_id=uuid.UUID(int=1000 + (source if source is not None else n)),
        url=f"https://example.com/{n}",
        title=f"Page {n}",
        publisher="example.com",
        tier=tier,
        text=text,
        score=0.03,
        vector_rank=1,
        keyword_rank=None,
    )


PASSAGES = {
    "P1": hit(1, "We spend most mornings reviewing eval results from the overnight run."),
    "P2": hit(2, "Our team reviews eval dashboards every morning before standup."),
    "P3": hit(3, "Honestly the evals are flaky and nobody trusts them.", tier="forum"),
    "P4": hit(4, "You will own 3 production services and their on-call rota.", tier="posting"),
}


def claim(text: str, *cites: tuple[str, str]) -> DraftClaim:
    return DraftClaim(text=text, citations=[DraftCitation(passage=p, quote=q) for p, q in cites])


def test_claims_are_kept_only_with_real_quotes_from_passages_shown() -> None:
    draft = SectionDraft(
        claims=[
            claim(
                "Practitioners describe reviewing evaluation results each morning.",
                ("P1", "reviewing eval results from the overnight run"),
                ("P2", "reviews eval dashboards every morning"),
                ("P2", "before standup"),  # a second quote from the same passage: one citation
            ),
            claim("Engineers review evals at night.", ("P9", "reviews evals at night")),
            claim("One engineer reviews dashboards nightly.", ("P2", "reviews dashboards nightly")),
            claim("A forum user calls the evals flaky.", ("P3", "the evals are flaky")),
            claim(
                "One posting asks the hire to own 4 production services.",
                ("P4", "own 3 production services"),
            ),
            claim(
                "One posting asks the hire to own 3 production services and on-call.",
                ("P4", "You will own 3 production services and their on-call rota"),
            ),
        ]
    )
    kept, dropped = rp.check_claims("day_to_day", draft, PASSAGES)
    assert [c.text for c in kept] == [
        "Practitioners describe reviewing evaluation results each morning.",
        "One posting asks the hire to own 3 production services and on-call.",
    ]
    assert [len(c.citations) for c in kept] == [2, 1]
    assert kept[0].citations[0].url == "https://example.com/1"
    assert [d.reason for d in dropped] == [
        "no valid citation (P9 was not one of the passages)",
        "no valid citation (the quote is not in P2)",
        "forum posts are never the only support",
        "the number 4 is not in a cited quote",
    ]


@pytest.mark.parametrize(
    ("text", "sources", "problem"),
    [
        ("Most teams run evals nightly.", 3, '"Most" claims a frequency'),
        ("Teams typically run evals nightly.", 3, '"typically" claims a frequency'),
        ("Teams often run evals nightly.", 1, '"often" needs at least two sources'),
        ("Teams often run evals nightly.", 2, None),
        ("Almost every team keeps an uncommon setup.", 1, None),  # word boundaries
        ("The same writer calls evals boring.", 1, '"The same writer" points back'),
        ("This team ships weekly.", 1, '"This team" points back'),
        ("They describe evals as boring.", 1, '"They" points back'),
        ("One blog says engineers review these evals daily.", 1, None),
        ("One posting says they will mentor others.", 1, None),  # "they" mid-sentence
        ("Cloud4C describes prompt work and a v2 pipeline.", 1, None),  # digits inside names
        ("Hallucinations cascade when several AI workflows are strung together.", 1, None),
        ("Several postings ask for evaluation work.", 1, '"Several postings" needs at least two'),
        ("Debugging takes 30% of the job.", 1, "the number 30 is not in a cited quote"),
    ],
)
def test_frequency_words_must_match_the_evidence(
    text: str, sources: int, problem: str | None
) -> None:
    found = rp.wording_problem(text, sources, quotes=[])
    assert (found is None) if problem is None else (found or "").startswith(problem)


def test_a_source_gets_one_number_however_many_of_its_passages_are_cited() -> None:
    two_passages = SectionDraft(
        claims=[
            claim(
                "Two postings ask the hire to own production services and their on-call.",
                ("P5", "own 3 production services"),  # P5 and P6 share a posting
                ("P1", "reviewing eval results"),
                ("P6", "their on-call rota"),
            )
        ]
    )
    labelled = {
        "P1": PASSAGES["P1"],
        "P5": hit(5, "You will own 3 production services.", "posting", source=7),
        "P6": hit(6, "You will join their on-call rota.", "posting", source=7),
    }
    kept, _ = rp.check_claims("responsibilities", two_passages, labelled)
    earlier = claim("One posting asks for on-call.", ("P6", "their on-call rota"))
    first, _ = rp.check_claims("summary", SectionDraft(claims=[earlier]), labelled)
    draft = rp.ReportDraft(
        role="GenAI Engineer",
        role_slug=ROLE,
        stats_version=1,
        country="GB",
        sample_size=20,
        employers=14,
        date_range=(date(2026, 5, 4), date(2026, 10, 28)),
        headline="Based on 20 GB job postings.",
        asked_for=[],
        sections={"summary": first, "responsibilities": kept},
        not_covered={},
        dropped=[],
        passages_shown={},
        model="test",
        prompt_version=rp.WRITER_VERSION,
        cost_usd=0.0,
    )
    markdown = rp.to_markdown(draft)
    # The posting was numbered 1 in the summary; the blog is 2. Sorted, never repeated.
    assert "- One posting asks for on-call. [1]" in markdown
    assert "their on-call. [1][2]" in markdown
    assert "1. job posting · example.com · Page 6: https://example.com/6" in markdown


# ---------------------------------------------------------------------- a whole draft


@pytest.fixture
def _no_versions(_db: None) -> None:
    with session_scope() as session:
        session.execute(delete(ArchetypeVersion))


_PASSAGE = re.compile(r"^\[(P\d+)\] [^\n]*\n([^\n]+)", re.MULTILINE)


def fake_writer(**kwargs: Any) -> SimpleNamespace:
    """Cites the first passage it is shown with a real quote, and invents one citation."""
    user = kwargs["messages"][-1]["content"]
    section = re.search(r"^Section: (.+)$", user, re.MULTILINE)
    assert section and "Passages:" in user
    label, text = _PASSAGE.findall(user)[0]
    quote = " ".join(text.split()[:6])
    reply = SectionDraft(
        claims=[
            claim(f"One source on {section.group(1).lower()} says: {quote}.", (label, quote)),
            claim("An invented claim about the role.", ("P99", "words nobody wrote")),
        ],
        not_covered="Nothing about salaries." if "day to day" in section.group(1) else None,
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=reply.model_dump_json()))],
        usage=SimpleNamespace(prompt_tokens=6000, completion_tokens=1500),
    )


async def _completion(**kwargs: Any) -> SimpleNamespace:
    return fake_writer(**kwargs)


def writer_gateway() -> LLMGateway:
    return LLMGateway(
        settings=Settings(_env_file=None),
        completion_fn=_completion,
        tracer=NoopTracer(),
        budgets=BudgetRegistry(Decimal("5")),
        embed_fn=bag_of_words,
    )


@pytest.mark.db
@pytest.mark.usefixtures("_db", "_no_versions")
async def test_a_draft_is_written_from_checked_evidence_only() -> None:
    counted = add_posting(
        "You will build retrieval pipelines and evaluation suites for our LLM features."
    )
    _decide(counted, True, 0.9)
    rejected = add_posting("You will build retrieval pipelines for our sales team's CRM.")
    _decide(rejected, False, 0.9)
    blog = add_page(
        "## Our week\n\nWe spend Monday on evals, then build and ship LLM features in practice."
    )
    with session_scope() as session:
        archetype_id = seed_roles(session, load_roles())[ROLE]
        save_version(session, archetype_id, stats([stat("Python", 0.8), stat("RAG", 0.4)]))
    await index_evidence(writer_gateway())

    draft = await rp.draft_report(writer_gateway(), ROLE)

    assert draft.headline.startswith("Based on 20 GB job postings from 14 employers")
    assert [s.label for s in draft.asked_for] == ["Python", "RAG"]
    [responsibility] = draft.sections["responsibilities"]
    assert {c.source_id for c in responsibility.citations} == {counted.source_id}
    for name in ("day_to_day", "pain_points"):
        assert {c.source_id for c in draft.sections[name][0].citations} == {blog}
    assert "typical_week" not in draft.sections  # folded into day to day for now
    assert draft.not_covered["day_to_day"] == "Nothing about salaries."
    # The summary is written from the surviving claims, with those claims' passages.
    [summary] = draft.sections["summary"]
    assert summary.citations[0].source_id in {counted.source_id, blog}
    # Every invented citation was caught and reported, one per section.
    assert sorted(d.section for d in draft.dropped) == sorted(
        ["responsibilities", "day_to_day", "pain_points", "summary"]
    )
    assert draft.cost_usd == pytest.approx(4 * (6000 * 4 + 1500 * 20) / 1e6)

    markdown = rp.to_markdown(draft)
    assert markdown.startswith("# GenAI Engineer: Role Reality Report (draft, not yet verified)")
    assert "- Most roles ask for Python: 80% of 20 postings" in markdown
    assert "## Sources" in markdown and "## Left out by the checks" in markdown


@pytest.mark.db
@pytest.mark.usefixtures("_db", "_no_versions")
async def test_no_statistics_means_no_report() -> None:
    with pytest.raises(rp.NoStatisticsError, match="make research"):
        await rp.draft_report(writer_gateway(), ROLE)


def test_the_writer_prompt_has_one_section_rules_slot() -> None:
    from firstweek_research.extract import load_prompt

    system, user = load_prompt(rp.WRITER_VERSION)
    assert system.format(section_rules="- extra rule") and "{section_rules}" in system
    fields = set(re.findall(r"{(\w+)}", user))
    assert fields == {
        "role_name",
        "role_definition",
        "section_title",
        "section_purpose",
        "passages",
    }
    assert json.dumps(SectionDraft.model_json_schema())  # the contract the reply must match
