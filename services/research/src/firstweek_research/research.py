"""One research run for a role: collect, classify, extract, compute statistics.

Paid steps are cached: a posting already classified (for this role and classifier version)
or extracted (for this extractor version) is never sent to a model again.
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from decimal import Decimal

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from firstweek_core.config import Settings
from firstweek_core.contracts import ArchetypeStats, RoleMatch
from firstweek_core.db.models import (
    Extraction,
    ExtractionRun,
    JobPosting,
    PostingRoleMatch,
    Source,
)
from firstweek_core.db.session import session_scope
from firstweek_core.llm import BudgetExceededError, LLMGateway, StructuredOutputError
from firstweek_research.collect import CollectSummary, run_collect
from firstweek_research.extract import (
    CLASSIFIER_VERSION,
    EXTRACTOR_VERSION,
    ExtractionOutcome,
    PostingView,
    classify,
    extract,
)
from firstweek_research.roles import RoleDefinition, load_roles
from firstweek_research.stats import MATCH_CONFIDENCE, compute_stats, save_version
from firstweek_research.store import seed_roles
from firstweek_research.taxonomy import load_taxonomy, seed_taxonomy

CONCURRENCY = 4


@dataclass
class ResearchResult:
    role: str
    collect: CollectSummary | None
    classified: int = 0
    matched: int = 0
    extracted: int = 0
    failures: dict[str, str] = field(default_factory=dict)
    cost_usd: Decimal = Decimal(0)
    stats: ArchetypeStats | None = None
    version: int | None = None


def _view(p: JobPosting) -> PostingView:
    return PostingView(str(p.id), str(p.source_id), p.title, p.company, p.text)


def candidates(session: Session, role: RoleDefinition, country: str) -> list[JobPosting]:
    """Full-text, unique postings whose title could be the role."""
    rows = session.scalars(
        select(JobPosting).where(
            JobPosting.country == country,
            JobPosting.is_full_text.is_(True),
            JobPosting.is_duplicate.is_(False),
        )
    ).all()
    return [p for p in rows if role.title_matches(p.title)]


@dataclass(frozen=True)
class MatchDecision:
    company: str | None
    title: str
    url: str
    counted: bool  # in the statistics sample: judged the role, confidence >= MATCH_CONFIDENCE
    is_match: bool | None  # None: not classified yet (for example, the call failed)
    confidence: float | None
    reason: str | None


def match_decisions(role_slug: str, country: str = "GB") -> list[MatchDecision]:
    """Every candidate posting for a role and what the classifier decided, for human review."""
    role = load_roles()[role_slug]
    with session_scope() as session:
        archetype_id = seed_roles(session, load_roles())[role_slug]
        decided = {
            m.posting_id: m
            for m in session.scalars(
                select(PostingRoleMatch).where(
                    PostingRoleMatch.archetype_id == archetype_id,
                    PostingRoleMatch.classifier_version == CLASSIFIER_VERSION,
                )
            )
        }
        pool = candidates(session, role, country)
        urls = {
            source_id: url
            for source_id, url in session.execute(
                select(Source.id, Source.url).where(Source.id.in_([p.source_id for p in pool]))
            )
        }
        rows = []
        for p in pool:
            m = decided.get(p.id)
            rows.append(
                MatchDecision(
                    company=p.company,
                    title=p.title,
                    url=urls.get(p.source_id, ""),
                    counted=bool(m and m.is_match and m.confidence >= MATCH_CONFIDENCE),
                    is_match=m.is_match if m else None,
                    confidence=m.confidence if m else None,
                    reason=m.reason if m else None,
                )
            )
    return sorted(rows, key=lambda r: (not r.counted, r.is_match is None, -(r.confidence or 0)))


async def _bounded[T](items: list[T], work: Callable[[T], Awaitable[None]]) -> None:
    gate = asyncio.Semaphore(CONCURRENCY)

    async def one(item: T) -> None:
        async with gate:
            await work(item)

    await asyncio.gather(*(one(i) for i in items))


async def run_research(
    role_slug: str,
    settings: Settings,
    gateway: LLMGateway,
    *,
    country: str = "GB",
    collect: bool = True,
    budget_usd: float = 5.0,
    use_boards: bool = True,
    use_adzuna: bool = True,
    use_web: bool = True,
    adzuna_pages: int = 2,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ResearchResult:
    roles = load_roles()
    role = roles[role_slug]
    taxonomy = load_taxonomy()
    scope = f"research:{role_slug}:{uuid.uuid4().hex[:8]}"
    gateway.budget(scope, Decimal(str(budget_usd)))
    result = ResearchResult(role=role.name, collect=None)

    if collect:
        result.collect = await run_collect(
            role_slug,
            settings,
            country=country,
            use_boards=use_boards,
            use_adzuna=use_adzuna,
            use_web=use_web,
            adzuna_pages=adzuna_pages,
            transport=transport,
        )

    with session_scope() as session:
        archetype_id = seed_roles(session, roles)[role_slug]
        skill_ids = seed_taxonomy(session, taxonomy)
        pool = candidates(session, role, country)
        done = set(
            session.scalars(
                select(PostingRoleMatch.posting_id).where(
                    PostingRoleMatch.archetype_id == archetype_id,
                    PostingRoleMatch.classifier_version == CLASSIFIER_VERSION,
                )
            )
        )
        to_classify = [_view(p) for p in pool if p.id not in done]

    # 1. Classify (role-specific).
    matches: dict[str, tuple[RoleMatch, str]] = {}

    async def do_classify(view: PostingView) -> None:
        try:
            matches[view.id] = await classify(gateway, role, view, budget_scope=scope)
        except (StructuredOutputError, BudgetExceededError) as exc:
            result.failures[f"classify:{view.title}"] = str(exc)[:200]

    await _bounded(to_classify, do_classify)
    with session_scope() as session:
        for posting_id, (match, model) in matches.items():
            session.add(
                PostingRoleMatch(
                    posting_id=uuid.UUID(posting_id),
                    archetype_id=archetype_id,
                    is_match=match.is_target_role,
                    confidence=match.confidence,
                    reason=match.reason,
                    classifier_version=CLASSIFIER_VERSION,
                    model=model,
                )
            )
        result.classified = len(matches)
        matched = session.scalars(
            select(JobPosting)
            .join(PostingRoleMatch, PostingRoleMatch.posting_id == JobPosting.id)
            .where(
                PostingRoleMatch.archetype_id == archetype_id,
                PostingRoleMatch.classifier_version == CLASSIFIER_VERSION,
                PostingRoleMatch.is_match.is_(True),
                PostingRoleMatch.confidence >= MATCH_CONFIDENCE,
                JobPosting.country == country,
            )
        ).all()
        result.matched = len(matched)
        extracted = set(
            session.scalars(
                select(ExtractionRun.source_id).where(
                    ExtractionRun.extractor_version == EXTRACTOR_VERSION
                )
            )
        )
        to_extract = [_view(p) for p in matched if p.source_id not in extracted]

    # 2. Extract (role-independent, once per posting).
    outcomes: dict[str, ExtractionOutcome] = {}

    async def do_extract(view: PostingView) -> None:
        try:
            outcomes[view.id] = await extract(gateway, view, taxonomy, budget_scope=scope)
        except (StructuredOutputError, BudgetExceededError) as exc:
            result.failures[f"extract:{view.title}"] = str(exc)[:200]

    await _bounded(to_extract, do_extract)
    views = {v.id: v for v in to_extract}
    with session_scope() as session:
        for posting_id, outcome in outcomes.items():
            source_id = uuid.UUID(views[posting_id].source_id)
            for item in outcome.items:
                session.add(
                    Extraction(
                        source_id=source_id,
                        kind=item.kind,
                        raw_text=item.label,
                        quote=item.quote,
                        skill_id=skill_ids.get(item.skill_slug) if item.skill_slug else None,
                        extractor_version=EXTRACTOR_VERSION,
                    )
                )
            session.add(
                ExtractionRun(
                    source_id=source_id,
                    extractor_version=EXTRACTOR_VERSION,
                    model=outcome.model,
                    items_kept=len(outcome.items),
                    items_dropped=len(outcome.dropped),
                )
            )
            posting = session.get(JobPosting, uuid.UUID(posting_id))
            if posting is not None:
                posting.seniority = outcome.seniority
        result.extracted = len(outcomes)

    # 3. Statistics, saved as a draft version for human review.
    with session_scope() as session:
        result.stats = compute_stats(session, role, archetype_id, country)
        version = save_version(session, archetype_id, result.stats)
        result.version = version.version if version else None

    result.cost_usd = gateway.budget(scope).spent_usd
    return result
