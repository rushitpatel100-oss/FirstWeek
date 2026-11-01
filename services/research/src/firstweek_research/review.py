"""Human review of stored reports: accept or reject each claim, spot-check the verifier by
hand, and publish (ADR 0015).

The verifier is a model, so before anything is published a person checks a sample of its
verdicts against the quotes. Publishing is gated on that sample, on every claim having a
decision, and removes rejected claims from the stored report. Nothing here calls a model.
"""

import random
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import func, select

from firstweek_core.contracts import RemovedClaim
from firstweek_core.db.models import (
    ArchetypeVersion,
    ReportClaim,
    RoleArchetype,
    RoleReport,
)
from firstweek_core.db.session import session_scope

Decision = Literal["accepted", "rejected"]
SECTION_ORDER = ("summary", "responsibilities", "day_to_day", "typical_week", "pain_points")
SPOT_CHECK_TARGET = 50  # the plan: 50 verified claims checked by hand before publishing
SPOT_CHECK_MAX_WRONG = 0.10  # more than this share wrong means the verifier is not trusted yet


class ReviewError(Exception):
    """Something the reviewer can fix: an unknown report, an undecided claim, a closed gate."""


@dataclass(frozen=True)
class Quote:
    publisher: str
    tier: str
    url: str
    text: str


@dataclass
class ReviewClaim:
    id: uuid.UUID
    section: str
    text: str
    confidence: float
    verification: str
    review: str
    note: str | None
    spot_check: str | None
    quotes: list[Quote] = field(default_factory=list)


@dataclass(frozen=True)
class SpotCheckStatus:
    checked: int
    wrong: int
    target: int = SPOT_CHECK_TARGET

    @property
    def wrong_share(self) -> float:
        return self.wrong / self.checked if self.checked else 0.0

    @property
    def passed(self) -> bool:
        return self.checked >= self.target and self.wrong_share <= SPOT_CHECK_MAX_WRONG


def latest_report_id(slug: str) -> uuid.UUID:
    """The newest stored report for a role."""
    with session_scope() as session:
        found = session.execute(
            select(RoleReport.id)
            .join(ArchetypeVersion, ArchetypeVersion.id == RoleReport.archetype_version_id)
            .join(RoleArchetype, RoleArchetype.id == ArchetypeVersion.archetype_id)
            .where(RoleArchetype.slug == slug)
            .order_by(RoleReport.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
    if found is None:
        raise ReviewError(f"No stored report for {slug}. Run `make report` first.")
    return found


def _quotes_by_claim(report: dict[str, Any]) -> dict[tuple[str, str], list[Quote]]:
    found: dict[tuple[str, str], list[Quote]] = {}
    for section in SECTION_ORDER:
        for claim in report.get(section) or []:
            found[(section, claim["text"])] = [
                Quote(_publisher(c["source_url"]), c["tier"], c["source_url"], c["quote"])
                for c in claim["citations"]
            ]
    return found


def _publisher(url: str) -> str:
    host = url.split("//", 1)[-1].split("/", 1)[0]
    return host.removeprefix("www.")


def _to_claim(row: ReportClaim, quotes: dict[tuple[str, str], list[Quote]]) -> ReviewClaim:
    return ReviewClaim(
        id=row.id,
        section=row.section,
        text=row.text,
        confidence=row.confidence,
        verification=row.verification,
        review=row.review,
        note=row.review_note,
        spot_check=row.spot_check,
        quotes=quotes.get((row.section, row.text), []),
    )


def load_claims(report_id: uuid.UUID) -> list[ReviewClaim]:
    """Every claim of a report in reading order, with the quotes that back it."""
    with session_scope() as session:
        report = session.get(RoleReport, report_id)
        if report is None:
            raise ReviewError(f"No report {report_id}.")
        quotes = _quotes_by_claim(dict(report.report))
        rows = session.execute(
            select(ReportClaim).where(ReportClaim.report_id == report_id)
        ).scalars()
        claims = [_to_claim(r, quotes) for r in rows]
    order = {name: i for i, name in enumerate(SECTION_ORDER)}
    return sorted(claims, key=lambda c: (order.get(c.section, 99), -c.confidence))


def report_status(report_id: uuid.UUID) -> str:
    with session_scope() as session:
        report = session.get(RoleReport, report_id)
        if report is None:
            raise ReviewError(f"No report {report_id}.")
        return report.status


def decide(claim_id: uuid.UUID, decision: Decision, note: str | None = None) -> None:
    """Record accept or reject for one claim. A published report is frozen."""
    with session_scope() as session:
        claim = session.get(ReportClaim, claim_id)
        if claim is None:
            raise ReviewError(f"No claim {claim_id}.")
        report = session.get(RoleReport, claim.report_id)
        assert report is not None
        if report.status == "published":
            raise ReviewError("This report is published; write a new one to change it.")
        if decision == "rejected" and not (note and note.strip()):
            raise ReviewError("Say why the claim is rejected (one line).")
        claim.review = decision
        claim.review_note = note.strip() if note else None
        session.flush()
        pending = session.execute(
            select(func.count())
            .select_from(ReportClaim)
            .where(ReportClaim.report_id == report.id, ReportClaim.review == "pending")
        ).scalar_one()
        report.status = "draft" if pending else "reviewed"
        report.reviewed_at = None if pending else datetime.now(UTC)


def spot_check_sample(count: int, *, seed: int | None = None) -> list[ReviewClaim]:
    """Random verified claims nobody has spot-checked yet, across all stored reports."""
    with session_scope() as session:
        rows = list(
            session.execute(select(ReportClaim).where(ReportClaim.spot_check.is_(None))).scalars()
        )
        reports = {
            r.id: _quotes_by_claim(dict(r.report))
            for r in session.execute(
                select(RoleReport).where(RoleReport.id.in_({c.report_id for c in rows}))
            ).scalars()
        }
        claims = [_to_claim(c, reports[c.report_id]) for c in rows]
    random.Random(seed).shuffle(claims)
    return claims[:count]


def record_spot_check(claim_id: uuid.UUID, backs_claim: bool) -> None:
    with session_scope() as session:
        claim = session.get(ReportClaim, claim_id)
        if claim is None:
            raise ReviewError(f"No claim {claim_id}.")
        claim.spot_check = "ok" if backs_claim else "wrong"


def spot_check_status() -> SpotCheckStatus:
    with session_scope() as session:
        rows = session.execute(
            select(ReportClaim.spot_check, func.count())
            .where(ReportClaim.spot_check.is_not(None))
            .group_by(ReportClaim.spot_check)
        ).all()
    counts = {k: n for k, n in rows}
    return SpotCheckStatus(
        checked=counts.get("ok", 0) + counts.get("wrong", 0), wrong=counts.get("wrong", 0)
    )


def publish_problems(report_id: uuid.UUID) -> list[str]:
    """Why this report cannot be published yet; empty when it can."""
    problems: list[str] = []
    with session_scope() as session:
        report = session.get(RoleReport, report_id)
        if report is None:
            return [f"No report {report_id}."]
        if report.status == "published":
            return ["Already published."]
        counts = dict(
            session.execute(
                select(ReportClaim.review, func.count())
                .where(ReportClaim.report_id == report_id)
                .group_by(ReportClaim.review)
            ).all()
        )
    if counts.get("pending"):
        problems.append(f"{counts['pending']} claims have no decision yet (`make review-report`).")
    if not counts.get("accepted"):
        problems.append("No claim is accepted.")
    status = spot_check_status()
    if status.checked < status.target:
        problems.append(
            f"Spot-check {status.target - status.checked} more claims by hand "
            f"({status.checked} of {status.target} done): `make spot-check`."
        )
    elif status.wrong_share > SPOT_CHECK_MAX_WRONG:
        problems.append(
            f"The spot-check found {status.wrong} of {status.checked} verdicts wrong "
            f"(more than {SPOT_CHECK_MAX_WRONG:.0%}): the verifier is not trusted yet."
        )
    return problems


def publish(report_id: uuid.UUID) -> int:
    """Publish a reviewed report without its rejected claims; returns how many were removed."""
    if problems := publish_problems(report_id):
        raise ReviewError(" ".join(problems))
    with session_scope() as session:
        report = session.get(RoleReport, report_id)
        assert report is not None
        rejected = {
            (c.section, c.text): c.review_note or ""
            for c in session.execute(
                select(ReportClaim).where(
                    ReportClaim.report_id == report_id, ReportClaim.review == "rejected"
                )
            ).scalars()
        }
        stored = dict(report.report)
        for section in SECTION_ORDER:
            stored[section] = [
                c for c in stored.get(section) or [] if (section, c["text"]) not in rejected
            ]
        provenance = stored.get("provenance")
        if provenance is not None:  # every report made by `make report` has one
            review_removals = [
                RemovedClaim(section=section, text=text, stage="review", reason=note).model_dump(
                    mode="json"
                )
                for (section, text), note in rejected.items()
            ]
            stored["provenance"] = {
                **provenance,
                "removed": [*(provenance.get("removed") or []), *review_removals],
            }
        report.report = stored
        report.status = "published"
        report.published_at = datetime.now(UTC)
        return len(rejected)
