"""The verifier: the confidence formula, what is removed, failing closed, and a verified
report stored end to end (a fake writer and a fake judge over a test database)."""

import re
import uuid
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import func, select, update
from test_passages import add_page, add_posting, bag_of_words, db_fixture
from test_report import ROLE, _no_versions, fake_writer, stat, stats
from test_retrieve import _decide

from firstweek_core.config import Settings
from firstweek_core.contracts import CitationCheck, ClaimCheck, RoleRealityReport, VerifierReply
from firstweek_core.db.models import ReportClaim, RoleReport, Source
from firstweek_core.db.session import session_scope
from firstweek_core.llm import BudgetRegistry, LLMGateway
from firstweek_core.llm.tracing import NoopTracer
from firstweek_research import report as rp
from firstweek_research import verify as vf
from firstweek_research.__main__ import judge_problem
from firstweek_research.passages import index_evidence
from firstweek_research.report import CitedPassage, DraftedClaim
from firstweek_research.roles import load_roles
from firstweek_research.stats import save_version
from firstweek_research.store import seed_roles

__all__ = ["_no_versions", "db_fixture"]  # registers the fixtures here

JUDGE = Settings(_env_file=None).model_judge
TODAY = date(2026, 10, 31)
RECENT = TODAY - timedelta(days=30)
OLD = TODAY - timedelta(days=400)


def cited(
    n: int, tier: str = "posting", publisher: str | None = None, published: date | None = RECENT
) -> CitedPassage:
    return CitedPassage(
        passage_id=uuid.UUID(int=n),
        source_id=uuid.UUID(int=1000 + n),
        url=f"https://example.com/{n}",
        tier=tier,
        title=None,
        publisher=publisher or f"Employer {n}",
        quote="a quote",
        published=published,
    )


def verdicts(*pairs: tuple[CitedPassage, str]) -> dict[uuid.UUID, Any]:
    return {c.passage_id: v for c, v in pairs}


# ---------------------------------------------------------------------- the formula


def test_recent_evidence_counts_in_full_and_undated_counts_as_old() -> None:
    assert vf.recency(RECENT, TODAY) == 1.0
    assert vf.recency(OLD, TODAY) == vf.OLD_EVIDENCE
    assert vf.recency(None, TODAY) == vf.OLD_EVIDENCE


@pytest.mark.parametrize(
    ("citations", "given", "verification", "expected"),
    [
        # Three strong sources make a claim certain; more add nothing.
        ([cited(1), cited(2), cited(3), cited(4)], ["supports"] * 4, "supported", 1.0),
        # One posting alone is Low; two are Medium.
        ([cited(1)], ["supports"], "supported", 0.333),
        ([cited(1), cited(2)], ["supports"] * 2, "supported", 0.667),
        # Two adverts from one employer are one source.
        (
            [cited(1, publisher="Acme"), cited(2, publisher="Acme")],
            ["supports"] * 2,
            "supported",
            0.333,
        ),
        # Tier weights: a blog 0.8, a forum 0.5.
        ([cited(1, "blog"), cited(2, "forum")], ["supports"] * 2, "supported", 0.433),
        # Old or undated evidence counts 0.7.
        ([cited(1, "blog", published=None)], ["supports"], "supported", 0.187),
        # "partly" counts half.
        ([cited(1)], ["partly"], "supported", 0.167),
        # A contradiction lowers agreement: 2 of 3 sources agree.
        (
            [cited(1), cited(2), cited(3)],
            ["supports", "supports", "contradicts"],
            "supported",
            0.444,
        ),
        # A partly supported claim is never High.
        ([cited(1), cited(2), cited(3)], ["supports"] * 3, "partial", vf.PARTIAL_CAP),
        ([cited(1), cited(2), cited(3)], ["supports"] * 3, "unsupported", 0.0),
    ],
)
def test_confidence_follows_the_plan(
    citations: list[CitedPassage], given: list[str], verification: Any, expected: float
) -> None:
    s = vf.score(citations, verdicts(*zip(citations, given, strict=True)), verification, TODAY)
    assert s.confidence == pytest.approx(expected, abs=1e-3)


def test_what_the_verifier_removes() -> None:
    blog, forum = cited(1, "blog"), cited(2, "forum")
    supported = vf.score([blog], verdicts((blog, "supports")), "supported", TODAY)
    assert vf.removal_reason("supported", "fine", supported) is None
    assert vf.removal_reason("unsupported", "P1 is about hiring", supported) == (
        "unsupported: P1 is about hiring"
    )
    nothing = vf.score([blog], verdicts((blog, "does_not_support")), "supported", TODAY)
    assert "no cited passage" in (vf.removal_reason("supported", "", nothing) or "")
    only_forum = vf.score(
        [blog, forum], verdicts((blog, "does_not_support"), (forum, "supports")), "partial", TODAY
    )
    assert "only forum posts" in (vf.removal_reason("partial", "", only_forum) or "")


# ---------------------------------------------------------------------- one section


def reply(checks: list[ClaimCheck]) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=VerifierReply(checks=checks).model_dump_json())
            )
        ],
        usage=SimpleNamespace(prompt_tokens=3000, completion_tokens=500),
    )


def gateway(completion: Any) -> LLMGateway:
    return LLMGateway(
        settings=Settings(_env_file=None),
        completion_fn=completion,
        tracer=NoopTracer(),
        budgets=BudgetRegistry(Decimal("5")),
        embed_fn=bag_of_words,
    )


async def test_a_claim_the_verifier_skips_is_removed_and_stray_labels_are_ignored() -> None:
    a, b = cited(1), cited(2)
    claims = [
        DraftedClaim(text="Postings ask for evaluation work.", citations=[a, b]),
        DraftedClaim(text="Postings ask for on-call.", citations=[b]),
    ]
    seen: list[str] = []

    async def judge(**kwargs: Any) -> SimpleNamespace:
        seen.append(kwargs["messages"][-1]["content"])
        assert kwargs["model"] == JUDGE
        return reply(
            [
                ClaimCheck(
                    claim="C1",
                    citations=[
                        CitationCheck(passage="P1", verdict="supports"),
                        CitationCheck(passage="P2", verdict="partly"),
                        CitationCheck(passage="P3", verdict="supports"),  # not cited: ignored
                    ],
                    verification="supported",
                    reason="P1 says so.",
                )
            ]
        )

    evidence = {a.passage_id: vf.Evidence("Build evaluation suites.", RECENT)}
    outcomes, model = await vf.check_section(
        gateway(judge),
        "GenAI Engineer",
        "responsibilities",
        "What employers say",
        claims,
        evidence,
        budget_scope="default",
    )
    assert model == JUDGE
    assert "[C1] Postings ask for evaluation work.\n  cites: P1, P2" in seen[0]
    assert "[P2] job posting · Employer 2\n(This passage is no longer in the evidence.)" in seen[0]
    assert outcomes[0].verdicts == {a.passage_id: "supports", b.passage_id: "partly"}
    assert outcomes[1].verification == "unsupported"  # fail closed
    assert outcomes[1].reason == "the verifier returned no verdict"


def test_the_verifier_must_be_another_family_and_have_its_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import firstweek_research.__main__ as cli

    def settings(**keys: str) -> Settings:
        return Settings(_env_file=None, **keys)  # type: ignore[arg-type]

    monkeypatch.setattr(cli, "get_settings", lambda: settings())
    assert "another model family" in (judge_problem("anthropic/claude-sonnet-5-5") or "")
    assert "GEMINI_API_KEY" in (judge_problem(JUDGE) or "")
    assert "aistudio.google.com" in (judge_problem(JUDGE) or "")
    assert "OPENAI_API_KEY" in (judge_problem("openai/gpt-6-sol") or "")
    monkeypatch.setattr(cli, "get_settings", lambda: settings(gemini_api_key="k"))
    assert judge_problem(JUDGE) is None


def test_the_free_judge_costs_nothing_and_stays_inside_any_budget() -> None:
    from firstweek_core.llm.pricing import cost_usd, is_known

    assert is_known(JUDGE) and cost_usd(JUDGE, 100_000, 10_000) == 0


def test_the_verifier_prompt_has_its_slots() -> None:
    from firstweek_research.extract import load_prompt

    system, user = load_prompt(vf.VERIFIER_VERSION)
    assert "{" not in system  # sent as is
    assert set(re.findall(r"{(\w+)}", user)) == {"role_name", "section_title", "claims", "passages"}


# ---------------------------------------------------------------------- a whole report


async def writer_and_judge(**kwargs: Any) -> SimpleNamespace:
    """Writes like test_report's fake writer; as the judge, backs every claim except those
    in "The hard parts", which it finds unsupported."""
    user = kwargs["messages"][-1]["content"]
    if "Claims:" not in user:
        return fake_writer(**kwargs)
    hard = "Section: The hard parts" in user
    checks = [
        ClaimCheck(
            claim=label,
            citations=[
                CitationCheck(passage=p.strip(), verdict="does_not_support" if hard else "supports")
                for p in refs.split(",")
            ],
            verification="unsupported" if hard else "supported",
            reason="The passage is about something else." if hard else "P1 says so.",
        )
        for label, refs in re.findall(r"^\[(C\d+)\] .*\n  cites: (.+)$", user, re.MULTILINE)
    ]
    return reply(checks)


@pytest.mark.db
@pytest.mark.usefixtures("_db", "_no_versions")
async def test_a_verified_report_is_scored_and_stored() -> None:
    counted = add_posting(
        "You will build retrieval pipelines and evaluation suites for our LLM features."
    )
    _decide(counted, True, 0.9)
    blog = add_page(
        "## Our week\n\nWe spend Monday on evals, then build and ship LLM features in practice."
    )
    with session_scope() as session:
        session.execute(update(Source).where(Source.id == blog).values(published_at=OLD))
        archetype_id = seed_roles(session, load_roles())[ROLE]
        save_version(session, archetype_id, stats([stat("Python", 0.8), stat("RAG", 0.4)]))
    g = gateway(writer_and_judge)
    await index_evidence(g)

    draft = await rp.draft_report(g, ROLE)
    verified = await vf.verify_report(g, draft, today=date.today())

    assert verified.verifier_model == JUDGE
    # The posting was seen yesterday: one recent posting is 1/3. The blog is over a year old.
    [job] = verified.sections["responsibilities"]
    assert job.confidence == pytest.approx(0.333, abs=1e-3) and job.verification == "supported"
    [day] = verified.sections["day_to_day"]
    assert day.confidence == pytest.approx(0.8 * 0.7 / 3, abs=1e-3)
    assert day.citations[0].published == OLD
    assert verified.sections["pain_points"] == []
    removed = [d for d in verified.dropped if d.stage == "verifier"]
    assert [(d.section, d.reason) for d in removed] == [
        ("pain_points", "unsupported: The passage is about something else.")
    ]
    assert len(verified.dropped) == len(draft.dropped) + 1  # the checks' removals are kept
    assert verified.cost_usd == pytest.approx(draft.cost_usd)  # the free judge adds nothing

    markdown = rp.to_markdown(verified)
    assert markdown.startswith("# GenAI Engineer: Role Reality Report (verified, not yet reviewed)")
    assert "· **Low** 0.33" in markdown and "## Removed by the verifier" in markdown

    report_id = vf.store_report(verified)
    with session_scope() as session:
        row = session.get(RoleReport, report_id)
        assert row is not None
        stored = RoleRealityReport.model_validate(row.report)
        claims = session.scalars(
            select(ReportClaim).where(ReportClaim.report_id == report_id)
        ).all()
        assert session.scalar(select(func.count()).select_from(RoleReport)) == 1
    kept = sum(len(c) for c in verified.sections.values())
    assert len(claims) == kept and {c.verification for c in claims} == {"supported"}
    assert stored.trust_level == "golden" and stored.typical_week == []
    assert stored.responsibilities[0].confidence == job.confidence
    assert stored.provenance is not None
    assert {r.stage for r in stored.provenance.removed} == {"checks", "verifier"}
