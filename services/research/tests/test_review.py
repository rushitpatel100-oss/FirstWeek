"""Human review: decisions, the spot-check, and the publish gate (a test database)."""

import uuid
from datetime import date

import pytest
from sqlalchemy import select, update
from test_passages import db_fixture
from test_report import ROLE, _no_versions, stat, stats

from firstweek_core.contracts import Citation, Claim, RoleRealityReport
from firstweek_core.db.models import ReportClaim, RoleReport
from firstweek_core.db.session import session_scope
from firstweek_research import review as rv
from firstweek_research import review_cli as cli
from firstweek_research.roles import load_roles
from firstweek_research.stats import save_version
from firstweek_research.store import seed_roles

__all__ = ["_no_versions", "db_fixture"]  # registers the fixtures here


def make_claim(text: str, quote: str) -> Claim:
    return Claim(
        text=text,
        citations=[
            Citation(
                source_url="https://blog.example.com/week",
                tier="blog",
                quote=quote,
            )
        ],
        confidence=0.4,
        verification="supported",
    )


def store(n_day_to_day: int = 3) -> uuid.UUID:
    """A stored report with one summary claim and n day-to-day claims."""
    claims = [
        make_claim(f"Claim number {i} about the week.", f"quote {i} words")
        for i in range(n_day_to_day)
    ]
    summary = [make_claim("The week is mostly evaluation work.", "evals every Monday")]
    with session_scope() as session:
        archetype_id = seed_roles(session, load_roles())[ROLE]
        version = save_version(session, archetype_id, stats([stat("Python", 0.8)]))
        assert version is not None
        report = RoleRealityReport(
            archetype="GenAI Engineer",
            trust_level="golden",
            version=1,
            country="GB",
            sample_size=20,
            date_range=(date(2026, 5, 1), date(2026, 10, 1)),
            summary=summary,
            asked_for=[],
            day_to_day=claims,
            typical_week=[],
            pain_points=[],
        )
        row = RoleReport(
            archetype_version_id=version.id,
            report=report.model_dump(mode="json"),
        )
        session.add(row)
        session.flush()
        for section, group in (("summary", summary), ("day_to_day", claims)):
            for c in group:
                session.add(
                    ReportClaim(
                        report_id=row.id,
                        section=section,
                        text=c.text,
                        confidence=c.confidence,
                        verification=c.verification,
                        passage_ids=[],
                    )
                )
        return row.id


def answers(*given: str):  # type: ignore[no-untyped-def]
    queue = list(given)

    def ask(_prompt: str) -> str:
        return queue.pop(0)

    return ask


@pytest.mark.db
@pytest.mark.usefixtures("_db", "_no_versions")
def test_claims_load_in_reading_order_with_their_quotes() -> None:
    report_id = store()
    claims = rv.load_claims(report_id)
    assert [c.section for c in claims] == ["summary", "day_to_day", "day_to_day", "day_to_day"]
    assert claims[0].quotes[0].text == "evals every Monday"
    assert claims[0].quotes[0].publisher == "blog.example.com"
    assert rv.latest_report_id(ROLE) == report_id


@pytest.mark.db
@pytest.mark.usefixtures("_db", "_no_versions")
def test_a_rejection_needs_a_reason_and_the_report_is_reviewed_when_all_are_decided() -> None:
    report_id = store(1)
    first, second = rv.load_claims(report_id)
    with pytest.raises(rv.ReviewError, match="why"):
        rv.decide(first.id, "rejected", "  ")
    rv.decide(first.id, "accepted")
    assert rv.report_status(report_id) == "draft"
    rv.decide(second.id, "rejected", "the quote is about a vendor")
    assert rv.report_status(report_id) == "reviewed"
    rv.decide(second.id, "accepted")  # changing your mind is allowed before publishing
    assert {c.review for c in rv.load_claims(report_id)} == {"accepted"}


@pytest.mark.db
@pytest.mark.usefixtures("_db", "_no_versions")
def test_the_terminal_loop_saves_each_answer_and_stops_when_asked() -> None:
    report_id = store(2)
    lines: list[str] = []
    cli.review_report(report_id, answers("a", "oops", "r", "", "r", "too thin", "q"), lines.append)
    states = [(c.review, c.note) for c in rv.load_claims(report_id)]
    assert states == [("accepted", None), ("rejected", "too thin"), ("pending", None)]
    assert "waiting 1" in lines[-1]


@pytest.mark.db
@pytest.mark.usefixtures("_db", "_no_versions")
def test_spot_check_hides_the_verdict_and_counts_wrong_answers() -> None:
    store(3)
    lines: list[str] = []
    cli.spot_check(3, answers("y", "n", "y"), lines.append, seed=1)
    assert not any("verifier:" in line for line in lines)
    status = rv.spot_check_status()
    assert (status.checked, status.wrong) == (3, 1)
    assert not status.passed
    assert len(rv.spot_check_sample(10)) == 1  # one claim is still unchecked


def check_many(n: int, wrong: int) -> None:
    with session_scope() as session:
        rows = list(session.execute(select(ReportClaim)).scalars())
        for i, row in enumerate(rows[:n]):
            row.spot_check = "wrong" if i < wrong else "ok"


@pytest.mark.db
@pytest.mark.usefixtures("_db", "_no_versions")
def test_publishing_is_gated_on_decisions_and_on_the_spot_check() -> None:
    report_id = store(60)
    problems = " ".join(rv.publish_problems(report_id))
    assert "61 claims have no decision" in problems and "Spot-check 50 more" in problems

    for c in rv.load_claims(report_id):
        rv.decide(c.id, "accepted")
    assert "Spot-check 50 more" in " ".join(rv.publish_problems(report_id))
    with pytest.raises(rv.ReviewError):
        rv.publish(report_id)

    check_many(50, wrong=10)  # 20% wrong: the verifier is not trusted
    assert "verdicts wrong" in " ".join(rv.publish_problems(report_id))

    with session_scope() as session:
        session.execute(update(ReportClaim).values(spot_check=None))
    check_many(50, wrong=3)
    assert rv.publish_problems(report_id) == []


@pytest.mark.db
@pytest.mark.usefixtures("_db", "_no_versions")
def test_publishing_removes_rejected_claims_and_freezes_the_report() -> None:
    report_id = store(60)
    claims = rv.load_claims(report_id)
    rv.decide(claims[1].id, "rejected", "vendor, not a practitioner")
    for c in claims:
        if c.id != claims[1].id:
            rv.decide(c.id, "accepted")
    check_many(50, wrong=0)

    assert rv.publish(report_id) == 1

    with session_scope() as session:
        row = session.get(RoleReport, report_id)
        assert row is not None
        assert row.status == "published" and row.published_at is not None
        stored = RoleRealityReport.model_validate(row.report)
    assert len(stored.day_to_day) == 59
    assert claims[1].text not in [c.text for c in stored.day_to_day]
    with pytest.raises(rv.ReviewError, match="published"):
        rv.decide(claims[0].id, "rejected", "changed my mind")
    assert rv.publish_problems(report_id) == ["Already published."]
