"""The claim verifier and confidence scores (ADR 0014).

A model from another family (the gateway's judge tier) reads every claim of a draft report
with the full text of the passages it cites, and labels each passage (supports, partly,
doesn't support, contradicts) and the claim as a whole (supported, partial, unsupported).
Code then decides what stays and scores it:

- unsupported claims are removed, and so are claims no cited passage supports or that only
  forum posts support;
- confidence follows the plan: c = min(1, sum of w * r / 3) * a, where w is the tier
  weight of each independent source that supports the claim (half for "partly"), r its
  recency and a the share of sources that support rather than contradict it;
- a partly supported claim is capped at 0.7, so it can never show as High.

A verified report is stored in role_reports (the RoleRealityReport contract, with what was
removed and why) and report_claims (one row per claim kept).
"""

import asyncio
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from firstweek_core.contracts import (
    TIER_WEIGHTS,
    Citation,
    CitationVerdict,
    Claim,
    ClaimCheck,
    RemovedClaim,
    ReportProvenance,
    ReportSection,
    RoleRealityReport,
    Verification,
    VerifierReply,
)
from firstweek_core.db.models import (
    ArchetypeVersion,
    EvidencePassage,
    JobPosting,
    ReportClaim,
    RoleArchetype,
    RoleReport,
    Source,
)
from firstweek_core.db.session import session_scope
from firstweek_core.llm import LLMGateway
from firstweek_core.llm import Tier as ModelTier
from firstweek_research.extract import load_prompt
from firstweek_research.report import (
    _TIER_NAMES,
    SECTIONS,
    SUMMARY,
    CitedPassage,
    DraftedClaim,
    DroppedClaim,
    ReportDraft,
)
from firstweek_research.roles import load_roles

VERIFIER_VERSION = "verify-claims.v1"
VERIFIER_TIER: ModelTier = "judge"  # another model family than the writer
VERIFIER_MAX_TOKENS = 8_000
STRONG_SOURCES = 3  # the plan: sources add up until three strong ones make a claim certain
RECENT_DAYS = 365  # evidence under 12 months old counts in full
OLD_EVIDENCE = 0.7  # older evidence, or evidence with no known date
PARTIAL_CAP = 0.7  # a partly supported claim is at most Medium
CREDIT: dict[CitationVerdict, float] = {
    "supports": 1.0,
    "partly": 0.5,
    "does_not_support": 0.0,
    "contradicts": 0.0,
}
_RANK: dict[CitationVerdict, int] = {
    "supports": 3,
    "partly": 2,
    "contradicts": 1,
    "does_not_support": 0,
}
_MISSING = "(This passage is no longer in the evidence.)"

# ---------------------------------------------------------------------- scoring


def recency(published: date | None, today: date) -> float:
    """Full weight for evidence under a year old. No known date counts as old: we can't
    claim evidence is current without knowing when it was written."""
    if published is not None and (today - published).days < RECENT_DAYS:
        return 1.0
    return OLD_EVIDENCE


def independent(citation: CitedPassage) -> str:
    """Two postings from one employer, or two pages from one site, are one source."""
    return f"{citation.tier}:{(citation.publisher or str(citation.source_id)).lower()}"


@dataclass(frozen=True)
class Score:
    confidence: float
    supporting: tuple[str, ...]  # the tier of each independent source that backs the claim
    contradicting: int


def score(
    citations: Sequence[CitedPassage],
    verdicts: Mapping[uuid.UUID, CitationVerdict],
    verification: Verification,
    today: date,
) -> Score:
    """The plan's confidence formula. A source's best verdict across its passages counts."""
    best: dict[str, tuple[CitationVerdict, CitedPassage]] = {}
    for c in citations:
        verdict = verdicts.get(c.passage_id, "does_not_support")
        key = independent(c)
        if key not in best or _RANK[verdict] > _RANK[best[key][0]]:
            best[key] = (verdict, c)
    total = 0.0
    supporting: list[str] = []
    contradicting = 0
    for verdict, c in best.values():
        if CREDIT[verdict] > 0:
            total += TIER_WEIGHTS[c.tier] * CREDIT[verdict] * recency(c.published, today)
            supporting.append(c.tier)
        elif verdict == "contradicts":
            contradicting += 1
    agreement = len(supporting) / (len(supporting) + contradicting) if supporting else 0.0
    confidence = min(1.0, total / STRONG_SOURCES) * agreement
    if verification == "partial":
        confidence = min(confidence, PARTIAL_CAP)
    elif verification == "unsupported":
        confidence = 0.0
    return Score(round(confidence, 3), tuple(supporting), contradicting)


def removal_reason(verification: Verification, reason: str, s: Score) -> str | None:
    if verification == "unsupported":
        return f"unsupported: {reason}"
    if not s.supporting:
        return "the verifier found no cited passage that supports it"
    if all(tier == "forum" for tier in s.supporting):
        return "only forum posts support it, and they are never the only support"
    return None


# ---------------------------------------------------------------------- checking


@dataclass(frozen=True)
class Evidence:
    text: str
    published: date | None


def load_evidence(passage_ids: set[uuid.UUID]) -> dict[uuid.UUID, Evidence]:
    """The full text of each cited passage and how current its source is. A posting counts
    from when it was last seen live, not when it was first published: an advert reposted
    for two years is still what the employer asks for today. A web page counts from its
    publication date, when known."""
    if not passage_ids:
        return {}
    with session_scope() as session:
        rows = session.execute(
            select(
                EvidencePassage.id,
                EvidencePassage.text,
                Source.tier,
                Source.published_at,
                JobPosting.last_seen_at,
            )
            .join(Source, Source.id == EvidencePassage.source_id)
            .outerjoin(JobPosting, JobPosting.source_id == Source.id)
            .where(EvidencePassage.id.in_(passage_ids))
        ).all()
    return {
        pid: Evidence(text, seen.date() if tier == "posting" and seen else published)
        for pid, text, tier, published, seen in rows
    }


@dataclass(frozen=True)
class Outcome:
    verification: Verification
    reason: str
    verdicts: dict[uuid.UUID, CitationVerdict]


def render(
    claims: Sequence[DraftedClaim], evidence: Mapping[uuid.UUID, Evidence]
) -> tuple[str, str, dict[str, uuid.UUID]]:
    """Claims C1, C2 ... with the labels of the passages they cite, and those passages."""
    labels: dict[uuid.UUID, str] = {}
    passages: list[str] = []
    lines: list[str] = []
    for i, claim in enumerate(claims, 1):
        refs = []
        for c in claim.citations:
            if c.passage_id not in labels:
                labels[c.passage_id] = f"P{len(labels) + 1}"
                who = " · ".join(p for p in (_TIER_NAMES[c.tier], c.publisher, c.title) if p)
                found = evidence.get(c.passage_id)
                text = found.text if found else _MISSING
                passages.append(f"[{labels[c.passage_id]}] {who}\n{text}")
            refs.append(labels[c.passage_id])
        lines.append(f"[C{i}] {claim.text}\n  cites: {', '.join(refs)}")
    return "\n\n".join(lines), "\n\n".join(passages), {v: k for k, v in labels.items()}


async def check_section(
    gateway: LLMGateway,
    role_name: str,
    section: ReportSection,
    title: str,
    claims: Sequence[DraftedClaim],
    evidence: Mapping[uuid.UUID, Evidence],
    *,
    budget_scope: str,
) -> tuple[list[Outcome], str]:
    claims_text, passages_text, by_label = render(claims, evidence)
    system, user = load_prompt(VERIFIER_VERSION)
    result = await gateway.structured(
        purpose=f"verify-report-{section}",
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": user.format(
                    role_name=role_name,
                    section_title=title,
                    claims=claims_text,
                    passages=passages_text,
                ),
            },
        ],
        response_model=VerifierReply,
        tier=VERIFIER_TIER,
        max_tokens=VERIFIER_MAX_TOKENS,
        budget_scope=budget_scope,
        prompt_version=VERIFIER_VERSION,
    )
    assert result.parsed is not None
    checks: dict[str, ClaimCheck] = {}
    for check in result.parsed.checks:
        checks.setdefault(check.claim, check)
    outcomes = []
    for i, claim in enumerate(claims, 1):
        found = checks.get(f"C{i}")
        if found is None:  # fail closed: a claim nobody checked is not kept
            outcomes.append(Outcome("unsupported", "the verifier returned no verdict", {}))
            continue
        cited = {c.passage_id for c in claim.citations}
        verdicts: dict[uuid.UUID, CitationVerdict] = {}
        for cc in found.citations:
            pid = by_label.get(cc.passage)
            if pid is not None and pid in cited:
                verdicts.setdefault(pid, cc.verdict)
        outcomes.append(Outcome(found.verification, found.reason.strip(), verdicts))
    return outcomes, result.model


async def verify_report(
    gateway: LLMGateway,
    draft: ReportDraft,
    *,
    budget_usd: float = 0.5,
    today: date | None = None,
) -> ReportDraft:
    """The draft with each kept claim labelled and scored, and removals listed with reasons."""
    today = today or date.today()
    scope = f"verify:{draft.role_slug}:{uuid.uuid4().hex[:8]}"
    gateway.budget(scope, Decimal(str(budget_usd)))
    evidence = load_evidence(
        {c.passage_id for claims in draft.sections.values() for k in claims for c in k.citations}
    )
    titles = {spec.name: spec.title for spec in (*SECTIONS, SUMMARY)}
    names = [name for name, claims in draft.sections.items() if claims]
    results = await asyncio.gather(
        *[
            check_section(
                gateway,
                draft.role,
                name,
                titles[name],
                draft.sections[name],
                evidence,
                budget_scope=scope,
            )
            for name in names
        ]
    )
    sections: dict[ReportSection, list[DraftedClaim]] = {name: [] for name in draft.sections}
    dropped = list(draft.dropped)
    models = {used for _, used in results} or {gateway.model_for(VERIFIER_TIER)}
    for name, (outcomes, _) in zip(names, results, strict=True):
        for claim, outcome in zip(draft.sections[name], outcomes, strict=True):
            dated = [
                c.model_copy(
                    update={"published": e.published if (e := evidence.get(c.passage_id)) else None}
                )
                for c in claim.citations
            ]
            s = score(dated, outcome.verdicts, outcome.verification, today)
            reason = removal_reason(outcome.verification, outcome.reason, s)
            if reason is not None:
                dropped.append(
                    DroppedClaim(section=name, text=claim.text, reason=reason, stage="verifier")
                )
                continue
            sections[name].append(
                claim.model_copy(
                    update={
                        "citations": dated,
                        "verification": outcome.verification,
                        "confidence": s.confidence,
                        "note": outcome.reason if outcome.verification == "partial" else None,
                    }
                )
            )
    return draft.model_copy(
        update={
            "sections": sections,
            "dropped": dropped,
            "verifier_model": ", ".join(sorted(models)),
            "verifier_prompt": VERIFIER_VERSION,
            "cost_usd": draft.cost_usd + float(gateway.budget(scope).spent_usd),
        }
    )


# ---------------------------------------------------------------------- storing


def to_report(draft: ReportDraft) -> RoleRealityReport:
    """The stored shape of a verified report (the plan's contract)."""
    assert draft.verifier_model is not None and draft.verifier_prompt is not None

    def claims(name: ReportSection) -> list[Claim]:
        return [
            Claim(
                text=c.text,
                citations=[
                    Citation(source_url=x.url, tier=x.tier, quote=x.quote, published=x.published)
                    for x in c.citations
                ],
                confidence=c.confidence if c.confidence is not None else 0.0,
                verification=c.verification or "unsupported",
            )
            for c in draft.sections.get(name, [])
        ]

    return RoleRealityReport(
        archetype=draft.role,
        trust_level=load_roles()[draft.role_slug].trust_level,
        version=draft.stats_version,
        country=draft.country,
        sample_size=draft.sample_size,
        date_range=draft.date_range,
        summary=claims("summary"),
        asked_for=draft.asked_for,
        responsibilities=claims("responsibilities"),
        day_to_day=claims("day_to_day"),
        typical_week=claims("typical_week"),
        pain_points=claims("pain_points"),
        provenance=ReportProvenance(
            stats_version=draft.stats_version,
            writer_model=draft.model,
            writer_prompt=draft.prompt_version,
            verifier_model=draft.verifier_model,
            verifier_prompt=draft.verifier_prompt,
            cost_usd=draft.cost_usd,
            removed=[
                RemovedClaim(section=d.section, text=d.text, stage=d.stage, reason=d.reason)
                for d in draft.dropped
            ],
        ),
    )


def store_report(draft: ReportDraft) -> uuid.UUID:
    """Saves a verified report against the statistics version it was written from."""
    report = to_report(draft)
    with session_scope() as session:
        version_id = session.execute(
            select(ArchetypeVersion.id)
            .join(RoleArchetype, RoleArchetype.id == ArchetypeVersion.archetype_id)
            .where(
                RoleArchetype.slug == draft.role_slug,
                ArchetypeVersion.version == draft.stats_version,
            )
        ).scalar_one()
        row = RoleReport(archetype_version_id=version_id, report=report.model_dump(mode="json"))
        session.add(row)
        session.flush()
        for name, claims in draft.sections.items():
            for c in claims:
                session.add(
                    ReportClaim(
                        report_id=row.id,
                        section=name,
                        text=c.text,
                        confidence=c.confidence if c.confidence is not None else 0.0,
                        verification=c.verification or "unsupported",
                        passage_ids=[str(x.passage_id) for x in c.citations],
                    )
                )
        return row.id
