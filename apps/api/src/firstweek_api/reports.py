"""Published Role Reality Reports, read-only. Drafts and unreviewed reports never leave the
database: only a report a person published (ADR 0015) is served."""

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from firstweek_core.contracts import RoleRealityReport
from firstweek_core.db.models import ArchetypeVersion, RoleArchetype, RoleReport
from firstweek_core.db.session import session_scope

router = APIRouter(prefix="/roles", tags=["reports"])


class RoleSummary(BaseModel):
    slug: str
    name: str
    country: str
    sample_size: int
    published_at: datetime


class PublishedReport(BaseModel):
    report_id: uuid.UUID
    slug: str
    name: str
    published_at: datetime
    report: RoleRealityReport


def _newest_published(slug: str | None = None) -> list[tuple[RoleArchetype, RoleReport]]:
    """The newest published report of each role (or of one role)."""
    with session_scope() as session:
        query = (
            select(RoleArchetype, RoleReport)
            .join(ArchetypeVersion, ArchetypeVersion.archetype_id == RoleArchetype.id)
            .join(RoleReport, RoleReport.archetype_version_id == ArchetypeVersion.id)
            .where(RoleReport.status == "published")
            .order_by(RoleReport.published_at.desc())
        )
        if slug is not None:
            query = query.where(RoleArchetype.slug == slug)
        newest: dict[str, tuple[RoleArchetype, RoleReport]] = {}
        for role, report in session.execute(query).all():
            newest.setdefault(role.slug, (role, report))
        session.expunge_all()
        return sorted(newest.values(), key=lambda pair: pair[0].name)


@router.get("")
def list_roles() -> list[RoleSummary]:
    """Roles that have a published report."""
    found = []
    for role, row in _newest_published():
        report = RoleRealityReport.model_validate(row.report)
        assert row.published_at is not None
        found.append(
            RoleSummary(
                slug=role.slug,
                name=role.name,
                country=report.country,
                sample_size=report.sample_size,
                published_at=row.published_at,
            )
        )
    return found


@router.get("/{slug}/report")
def get_report(slug: str) -> PublishedReport:
    """The newest published report for a role; 404 until one is published."""
    found = _newest_published(slug)
    if not found:
        raise HTTPException(status_code=404, detail="No published report for this role yet.")
    role, row = found[0]
    assert row.published_at is not None
    return PublishedReport(
        report_id=row.id,
        slug=role.slug,
        name=role.name,
        published_at=row.published_at,
        report=RoleRealityReport.model_validate(row.report),
    )
