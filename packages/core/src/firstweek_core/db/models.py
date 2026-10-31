"""SQLAlchemy models for every table in the plan's data model.

Two rules shape the schema:
- Research data (roles, sources, evidence, archetype versions) is shared and versioned.
- Simulation data (simulations, tickets, messages, submissions) belongs to one user.
Every report claim links to passages, and every passage links to its source.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from firstweek_core.db.base import EMBEDDING_DIM, Base, IdMixin, TimestampMixin

JSON = dict[str, Any]
JSONList = list[Any]


# ---------------------------------------------------------------- Research


class RoleArchetype(IdMixin, TimestampMixin, Base):
    __tablename__ = "role_archetypes"
    __table_args__ = (CheckConstraint("trust_level IN ('golden', 'on_demand')", name="trust"),)

    slug: Mapped[str] = mapped_column(String(120), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    definition: Mapped[str] = mapped_column(Text)
    trust_level: Mapped[str] = mapped_column(String(16), default="on_demand")
    seniority_levels: Mapped[JSONList] = mapped_column(JSONB, default=list)


class RoleAlias(IdMixin, Base):
    __tablename__ = "role_aliases"

    archetype_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("role_archetypes.id", ondelete="CASCADE"), index=True
    )
    alias: Mapped[str] = mapped_column(String(200))
    normalized_alias: Mapped[str] = mapped_column(String(200), unique=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)


class Source(IdMixin, Base):
    """One fetched document. A URL maps to one row; a content change updates it in place."""

    __tablename__ = "sources"
    __table_args__ = (
        CheckConstraint("tier IN ('posting', 'blog', 'forum', 'interview')", name="tier"),
    )

    url: Mapped[str] = mapped_column(Text, unique=True)
    tier: Mapped[str] = mapped_column(String(16))
    provider: Mapped[str] = mapped_column(String(32), comment="greenhouse, adzuna, firecrawl...")
    title: Mapped[str | None] = mapped_column(Text)
    publisher: Mapped[str | None] = mapped_column(String(200))
    published_at: Mapped[date | None] = mapped_column(Date)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    content_hash: Mapped[str] = mapped_column(String(64), comment="sha256 of the cleaned content")
    content: Mapped[str] = mapped_column(Text, comment="Cleaned text or markdown")
    licence_note: Mapped[str] = mapped_column(Text)
    raw_uri: Mapped[str | None] = mapped_column(Text)


class JobPosting(IdMixin, Base):
    __tablename__ = "job_postings"
    __table_args__ = (UniqueConstraint("provider", "external_id"),)

    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), unique=True
    )
    provider: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(String(300))
    company: Mapped[str | None] = mapped_column(String(300))
    department: Mapped[str | None] = mapped_column(String(300))
    location: Mapped[str | None] = mapped_column(String(300))
    country: Mapped[str] = mapped_column(String(2))
    workplace: Mapped[str | None] = mapped_column(String(16), comment="onsite, hybrid or remote")
    posted_at: Mapped[date | None] = mapped_column(Date)
    salary_min: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    salary_max: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    salary_currency: Mapped[str | None] = mapped_column(String(3))
    is_full_text: Mapped[bool] = mapped_column(
        Boolean, default=True, comment="False for search-API snippets (Adzuna: ~500 chars)"
    )
    seniority: Mapped[str | None] = mapped_column(String(16))
    archetype_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("role_archetypes.id", ondelete="SET NULL"), index=True
    )
    dedup_group: Mapped[uuid.UUID | None] = mapped_column(index=True)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    text: Mapped[str] = mapped_column(Text)


class TaxonomySkill(IdMixin, Base):
    __tablename__ = "taxonomy_skills"
    __table_args__ = (
        CheckConstraint("origin IN ('esco', 'ai_extension')", name="origin"),
        CheckConstraint("kind IN ('skill', 'tool')", name="kind"),
    )

    slug: Mapped[str] = mapped_column(String(80), unique=True, comment="Stable id, e.g. 'rag'")
    kind: Mapped[str] = mapped_column(String(16), default="skill")
    esco_uri: Mapped[str | None] = mapped_column(Text, unique=True)
    label: Mapped[str] = mapped_column(String(300))
    aliases: Mapped[JSONList] = mapped_column(JSONB, default=list)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("taxonomy_skills.id", ondelete="SET NULL")
    )
    origin: Mapped[str] = mapped_column(String(16))


class Extraction(IdMixin, TimestampMixin, Base):
    __tablename__ = "extractions"
    __table_args__ = (
        CheckConstraint("kind IN ('skill', 'tool', 'responsibility', 'challenge')", name="kind"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16))
    raw_text: Mapped[str] = mapped_column(Text)
    quote: Mapped[str] = mapped_column(Text)
    skill_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("taxonomy_skills.id", ondelete="SET NULL"), index=True
    )
    extractor_version: Mapped[str] = mapped_column(String(64))


class ExtractionRun(IdMixin, TimestampMixin, Base):
    """One extraction of one source by one extractor version, even if it found nothing."""

    __tablename__ = "extraction_runs"
    __table_args__ = (UniqueConstraint("source_id", "extractor_version"),)

    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"))
    extractor_version: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    items_kept: Mapped[int] = mapped_column(Integer, default=0)
    items_dropped: Mapped[int] = mapped_column(
        Integer, default=0, comment="Quote not found verbatim in the posting"
    )


class PostingRoleMatch(IdMixin, TimestampMixin, Base):
    """Whether a posting describes a role, as judged against the role's definition."""

    __tablename__ = "posting_role_matches"
    __table_args__ = (
        UniqueConstraint("posting_id", "archetype_id", "classifier_version"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
    )

    posting_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job_postings.id", ondelete="CASCADE"), index=True
    )
    archetype_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("role_archetypes.id", ondelete="CASCADE"), index=True
    )
    is_match: Mapped[bool] = mapped_column(Boolean)
    confidence: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text)
    classifier_version: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))


class EvidencePassage(IdMixin, Base):
    __tablename__ = "evidence_passages"
    __table_args__ = (
        UniqueConstraint("source_id", "ordinal"),
        Index(
            "ix_evidence_passages_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"))
    ordinal: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)


class ArchetypeVersion(IdMixin, TimestampMixin, Base):
    __tablename__ = "archetype_versions"
    __table_args__ = (
        UniqueConstraint("archetype_id", "version"),
        CheckConstraint("status IN ('draft', 'reviewed', 'published')", name="status"),
    )

    archetype_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("role_archetypes.id", ondelete="CASCADE")
    )
    version: Mapped[int] = mapped_column(Integer)
    country: Mapped[str] = mapped_column(String(2))
    date_from: Mapped[date] = mapped_column(Date)
    date_to: Mapped[date] = mapped_column(Date)
    sample_size: Mapped[int] = mapped_column(Integer)
    stats: Mapped[JSON] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CompanyOverlay(IdMixin, TimestampMixin, Base):
    __tablename__ = "company_overlays"
    __table_args__ = (UniqueConstraint("archetype_version_id", "company"),)

    archetype_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("archetype_versions.id", ondelete="CASCADE")
    )
    company: Mapped[str] = mapped_column(String(300))
    findings: Mapped[JSON] = mapped_column(JSONB, default=dict)


# ---------------------------------------------------------------- Users and reports


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(200))
    background: Mapped[str | None] = mapped_column(Text)


class RoleReport(IdMixin, TimestampMixin, Base):
    __tablename__ = "role_reports"

    archetype_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("archetype_versions.id", ondelete="CASCADE"), index=True
    )
    overlay_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("company_overlays.id", ondelete="SET NULL")
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    user_background: Mapped[str | None] = mapped_column(Text)
    report: Mapped[JSON] = mapped_column(JSONB)


class ReportClaim(IdMixin, Base):
    __tablename__ = "report_claims"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        CheckConstraint(
            "verification IN ('supported', 'partial', 'unsupported')", name="verification"
        ),
    )

    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("role_reports.id", ondelete="CASCADE"), index=True
    )
    section: Mapped[str] = mapped_column(String(32))
    text: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    verification: Mapped[str] = mapped_column(String(16))
    passage_ids: Mapped[JSONList] = mapped_column(JSONB, default=list)


# ---------------------------------------------------------------- Simulation


class Blueprint(IdMixin, TimestampMixin, Base):
    __tablename__ = "blueprints"
    __table_args__ = (CheckConstraint("status IN ('draft', 'approved')", name="status"),)

    archetype_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("archetype_versions.id", ondelete="CASCADE"), index=True
    )
    scenario: Mapped[str] = mapped_column(Text)
    blueprint: Mapped[JSON] = mapped_column(JSONB, comment="ProjectBlueprint minus the answer key")
    answer_key: Mapped[JSON] = mapped_column(JSONB, comment="Evaluator-only")
    validated: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="draft")


class Simulation(IdMixin, TimestampMixin, Base):
    __tablename__ = "simulations"
    __table_args__ = (
        CheckConstraint("sim_day BETWEEN 1 AND 5", name="sim_day_range"),
        CheckConstraint(
            "status IN ('provisioning', 'ready', 'in_progress', 'evaluating', 'completed', "
            "'failed')",
            name="status",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    blueprint_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("blueprints.id"))
    seed: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="provisioning")
    sim_day: Mapped[int] = mapped_column(Integer, default=1)
    state: Mapped[JSON] = mapped_column(JSONB, default=dict, comment="ProjectState")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Ticket(IdMixin, Base):
    __tablename__ = "tickets"
    __table_args__ = (
        UniqueConstraint("simulation_id", "key"),
        CheckConstraint("status IN ('todo', 'in_progress', 'in_review', 'done')", name="status"),
    )

    simulation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("simulations.id", ondelete="CASCADE")
    )
    key: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text)
    acceptance_criteria: Mapped[JSONList] = mapped_column(JSONB)
    task_type: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="todo")
    due_day: Mapped[int] = mapped_column(Integer)


class Artifact(IdMixin, TimestampMixin, Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        CheckConstraint("simulation_id IS NOT NULL OR blueprint_id IS NOT NULL", name="has_owner"),
    )

    simulation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("simulations.id", ondelete="CASCADE"), index=True
    )
    blueprint_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("blueprints.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))
    storage_uri: Mapped[str] = mapped_column(Text)
    checksum: Mapped[str] = mapped_column(String(64))


class Message(IdMixin, TimestampMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_simulation_created", "simulation_id", "created_at"),)

    simulation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("simulations.id", ondelete="CASCADE")
    )
    channel: Mapped[str] = mapped_column(String(64))
    sender: Mapped[str] = mapped_column(String(64))
    body: Mapped[str] = mapped_column(Text)


class Submission(IdMixin, TimestampMixin, Base):
    __tablename__ = "submissions"

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))
    storage_uri: Mapped[str] = mapped_column(Text)
    commit_sha: Mapped[str | None] = mapped_column(String(64))


class SandboxRun(IdMixin, TimestampMixin, Base):
    __tablename__ = "sandbox_runs"

    submission_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("submissions.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(32))
    command: Mapped[str] = mapped_column(Text)
    exit_code: Mapped[int | None] = mapped_column(Integer)
    output_uri: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)


class EvaluationRecord(IdMixin, TimestampMixin, Base):
    __tablename__ = "evaluations"

    submission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("submissions.id", ondelete="CASCADE"), index=True
    )
    checks: Mapped[JSON] = mapped_column(JSONB)
    rubric_scores: Mapped[JSONList] = mapped_column(JSONB)
    judge_model: Mapped[str] = mapped_column(String(128))
    feedback: Mapped[str] = mapped_column(Text)


class SkillScore(IdMixin, Base):
    __tablename__ = "skill_scores"
    __table_args__ = (
        UniqueConstraint("simulation_id", "skill_id"),
        CheckConstraint("score BETWEEN 1 AND 5", name="score_range"),
    )

    simulation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("simulations.id", ondelete="CASCADE")
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("taxonomy_skills.id"))
    score: Mapped[int] = mapped_column(Integer)
    evidence_refs: Mapped[JSONList] = mapped_column(JSONB, default=list)


class PortfolioOutput(IdMixin, TimestampMixin, Base):
    __tablename__ = "portfolio_outputs"

    simulation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("simulations.id", ondelete="CASCADE"), unique=True
    )
    github_url: Mapped[str | None] = mapped_column(Text)
    cv_bullets: Mapped[JSONList] = mapped_column(JSONB, default=list)
    public_slug: Mapped[str] = mapped_column(String(64), unique=True)


# ---------------------------------------------------------------- Operations


class LLMCall(IdMixin, TimestampMixin, Base):
    __tablename__ = "llm_calls"
    __table_args__ = (Index("ix_llm_calls_scope_created", "budget_scope", "created_at"),)

    purpose: Mapped[str] = mapped_column(String(64))
    tier: Mapped[str] = mapped_column(String(16))
    model: Mapped[str] = mapped_column(String(128))
    budget_scope: Mapped[str] = mapped_column(String(128))
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal(0))
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[str | None] = mapped_column(String(64))
