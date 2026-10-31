"""Write collected evidence to Postgres. Every write is idempotent: re-running a collection
updates what changed and leaves the rest alone."""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from firstweek_core.db.models import Extraction, JobPosting, RoleAlias, RoleArchetype, Source
from firstweek_research.clean import CleanResult, content_hash, normalize_whitespace
from firstweek_research.dedup import DedupDoc, DedupResult, find_duplicates
from firstweek_research.roles import RoleDefinition, normalize_title
from firstweek_research.sources.base import RawPosting, WebDocument

Status = Literal["new", "updated", "unchanged"]
LEVELS = ["junior", "mid", "senior", "lead", "principal"]


@dataclass(frozen=True)
class PreparedPosting:
    raw: RawPosting
    clean: CleanResult
    country: str


def seed_roles(session: Session, roles: dict[str, RoleDefinition]) -> dict[str, uuid.UUID]:
    """Create or update role archetypes and their aliases from the YAML definitions."""
    ids: dict[str, uuid.UUID] = {}
    for role in roles.values():
        archetype = session.scalar(select(RoleArchetype).where(RoleArchetype.slug == role.slug))
        if archetype is None:
            archetype = RoleArchetype(slug=role.slug)
            session.add(archetype)
        archetype.name = role.name
        archetype.definition = role.definition
        archetype.trust_level = role.trust_level
        archetype.seniority_levels = LEVELS
        session.flush()
        ids[role.slug] = archetype.id
        for alias in dict.fromkeys([role.name, *role.aliases]):
            key = normalize_title(alias)
            existing = session.scalar(select(RoleAlias).where(RoleAlias.normalized_alias == key))
            if existing is None:
                session.add(RoleAlias(archetype_id=archetype.id, alias=alias, normalized_alias=key))
            else:
                existing.archetype_id, existing.alias = archetype.id, alias
    session.flush()
    return ids


def _touch_source(
    session: Session,
    source: Source | None,
    *,
    url: str,
    tier: str,
    provider: str,
    title: str | None,
    publisher: str | None,
    published_at: date | None,
    content: str,
    licence_note: str,
) -> tuple[Source, Status]:
    digest = content_hash(content)
    now = datetime.now(UTC)
    if source is None:
        source = Source(
            url=url,
            tier=tier,
            provider=provider,
            title=title,
            publisher=publisher,
            published_at=published_at,
            content_hash=digest,
            content=content,
            licence_note=licence_note,
            fetched_at=now,
        )
        session.add(source)
        session.flush()
        return source, "new"
    source.fetched_at = now  # records that we saw it again
    if source.content_hash == digest:
        return source, "unchanged"
    source.content, source.content_hash, source.title = content, digest, title
    # Extractions describe the old text; they must be redone.
    session.execute(delete(Extraction).where(Extraction.source_id == source.id))
    return source, "updated"


def upsert_posting(session: Session, item: PreparedPosting) -> Status:
    raw = item.raw
    posting = session.scalar(
        select(JobPosting).where(
            JobPosting.provider == raw.provider, JobPosting.external_id == raw.external_id
        )
    )
    source = session.get(Source, posting.source_id) if posting else None
    if source is None:
        source = session.scalar(select(Source).where(Source.url == raw.url))
        owner = source and session.scalar(
            select(JobPosting).where(JobPosting.source_id == source.id)
        )
        if owner is not None:
            return "unchanged"  # same URL already stored under another provider id
    source, status = _touch_source(
        session,
        source,
        url=raw.url,
        tier="posting",
        provider=raw.provider,
        title=raw.title,
        publisher=raw.company,
        published_at=raw.posted_at,
        content=item.clean.full_text,
        licence_note=raw.licence_note,
    )
    if posting is None:
        posting = JobPosting(
            source_id=source.id, provider=raw.provider, external_id=raw.external_id
        )
        session.add(posting)
    elif status == "unchanged":
        if posting.text == item.clean.role_text:
            return status
        # Same source text, but the cleaning rules changed what counts as role text.
        session.execute(delete(Extraction).where(Extraction.source_id == source.id))
        status = "updated"
    posting.title = raw.title[:300]
    posting.company = raw.company.strip()[:300] if raw.company else None
    posting.department = raw.department[:300] if raw.department else None
    posting.location = "; ".join(raw.locations)[:300] or None
    posting.country = item.country
    posting.workplace = raw.workplace
    posting.posted_at = raw.posted_at
    posting.salary_min, posting.salary_max = raw.salary_min, raw.salary_max
    posting.salary_currency = raw.salary_currency
    posting.is_full_text = raw.is_full_text
    posting.text = item.clean.role_text
    session.flush()
    return status


def upsert_web_document(session: Session, doc: WebDocument) -> Status:
    source = session.scalar(select(Source).where(Source.url == doc.url))
    _, status = _touch_source(
        session,
        source,
        url=doc.url,
        tier=doc.tier,
        provider="firecrawl",
        title=doc.title,
        publisher=doc.publisher,
        published_at=None,
        content=normalize_whitespace(doc.markdown),
        licence_note=doc.licence_note,
    )
    return status


def apply_dedup(session: Session, country: str) -> DedupResult:
    """Recompute duplicate groups across every stored posting in the country."""
    rows = session.execute(
        select(
            JobPosting.id,
            JobPosting.text,
            JobPosting.title,
            JobPosting.company,
            JobPosting.is_full_text,
            JobPosting.posted_at,
        ).where(JobPosting.country == country)
    ).all()
    docs = [
        DedupDoc(str(r.id), r.text, r.title, r.company, r.is_full_text, r.posted_at) for r in rows
    ]
    result = find_duplicates(docs)
    for doc_id, group in result.group_of.items():
        session.execute(
            update(JobPosting)
            .where(JobPosting.id == uuid.UUID(doc_id))
            .values(dedup_group=uuid.UUID(group), is_duplicate=doc_id in result.duplicates)
        )
    session.flush()
    return result
