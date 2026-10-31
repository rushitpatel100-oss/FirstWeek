"""Activities for the daily research run. Each wraps a step of firstweek_research.

All are safe to retry: collection is idempotent (it upserts), analysis saves each paid model
result as it arrives, so a retry only pays for what the failed attempt did not finish, and
indexing skips every source whose passages are already current.
Progress messages become Temporal heartbeats, so a stuck step is noticed and retried.
"""

import logging
from dataclasses import dataclass, field

from temporalio import activity
from temporalio.exceptions import ApplicationError

from firstweek_core.config import get_settings
from firstweek_core.llm import LLMGateway
from firstweek_core.llm.recorder import record_to_db
from firstweek_research.collect import run_collect
from firstweek_research.passages import index_evidence as run_index_evidence
from firstweek_research.research import code_fingerprint, run_research

log = logging.getLogger("firstweek.research")


@dataclass
class RoleRunInput:
    role_slug: str
    country: str = "GB"
    budget_usd: float = 1.0


@dataclass
class CollectOutcome:
    role_slug: str
    new: int = 0
    updated: int = 0
    errors: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


@dataclass
class AnalyseOutcome:
    role_slug: str
    classified: int = 0
    matched: int = 0
    extracted: int = 0
    cost_usd: float = 0.0
    sample_size: int = 0
    employers: int = 0
    version: int | None = None
    failures: list[str] = field(default_factory=list)
    skipped: str | None = None


@dataclass
class EvidenceOutcome:
    model: str
    sources: int = 0
    indexed: int = 0
    passages_added: int = 0
    sources_removed: int = 0


def _heartbeat(message: str) -> None:
    log.info(message)
    activity.heartbeat(message)


CODE_MISMATCH = "CodeVersionMismatch"


@activity.defn(name="check_code_version")
async def check_code_version(expected: str) -> str:
    """Fails fast when the worker's research code differs from the caller's, instead of
    quietly running old definitions (seen 2026-10-31: a worker image built before a pull)."""
    actual = code_fingerprint()
    if actual != expected:
        raise ApplicationError(
            f"The worker's research code ({actual}) differs from yours ({expected}). "
            "Rebuild and restart it: docker compose up -d --build worker",
            type=CODE_MISMATCH,
            non_retryable=True,
        )
    return actual


@activity.defn(name="collect_role")
async def collect_role(inp: RoleRunInput) -> CollectOutcome:
    summary = await run_collect(
        inp.role_slug, get_settings(), country=inp.country, progress=_heartbeat
    )
    return CollectOutcome(
        role_slug=inp.role_slug,
        new=sum(s.new for s in summary.providers.values()),
        updated=sum(s.updated for s in summary.providers.values()),
        errors=[f"{name}: {error}" for name, error in summary.errors.items()],
        skipped=[f"{name}: {reason}" for name, reason in summary.skipped.items()],
    )


@activity.defn(name="analyse_role")
async def analyse_role(inp: RoleRunInput) -> AnalyseOutcome:
    settings = get_settings()
    if settings.anthropic_api_key is None:
        return AnalyseOutcome(inp.role_slug, skipped="ANTHROPIC_API_KEY is not set")
    gateway = LLMGateway(settings=settings, recorder=record_to_db)
    try:
        result = await run_research(
            inp.role_slug,
            settings,
            gateway,
            country=inp.country,
            collect=False,  # the collect_role activity has just done it
            budget_usd=inp.budget_usd,
            progress=_heartbeat,
        )
    finally:
        gateway.flush()
    stats = result.stats
    return AnalyseOutcome(
        role_slug=inp.role_slug,
        classified=result.classified,
        matched=result.matched,
        extracted=result.extracted,
        cost_usd=float(result.cost_usd),
        sample_size=stats.sample_size if stats else 0,
        employers=stats.employers if stats else 0,
        version=result.version,
        failures=[f"{name}: {error}" for name, error in result.failures.items()],
    )


@activity.defn(name="index_evidence")
async def index_evidence() -> EvidenceOutcome:
    """Passages and embeddings for new or changed sources. The embedding model runs inside
    the worker, so this costs nothing and needs no API key."""
    gateway = LLMGateway(settings=get_settings(), recorder=record_to_db)
    try:
        s = await run_index_evidence(gateway, progress=_heartbeat)
    finally:
        gateway.flush()
    return EvidenceOutcome(
        model=s.model,
        sources=s.sources,
        indexed=s.indexed,
        passages_added=s.passages_added,
        sources_removed=s.sources_removed,
    )
