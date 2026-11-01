"""The report writer: a draft Role Reality Report built only from evidence (ADR 0013).

Two kinds of content, kept apart:
- Numbers come from the role's statistics and are written by code, never by a model: the
  headline and "what employers ask for", worded by the plan's frequency bands.
- Prose sections come from a model that sees only retrieved passages. Each section has its
  own evidence tiers (postings say what employers ask for; blogs, forums and interviews say
  what the work is like), and the summary is written last, from the other sections' claims.

Every claim the model writes is checked before it is kept: each citation must name a passage
it was shown and quote it word for word, forum posts can't be the only support, numbers must
appear in a cited quote, and frequency words must match the number of sources. Claims that
fail are listed with the reason, never silently dropped. Checking whether each claim is
actually supported, and scoring confidence, comes next (the verifier).
"""

import asyncio
import re
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal, cast

from pydantic import BaseModel
from sqlalchemy import select

from firstweek_core.contracts import (
    ArchetypeStats,
    ReportSection,
    SectionDraft,
    SkillStat,
    Tier,
    Verification,
)
from firstweek_core.db.models import ArchetypeVersion, RoleArchetype
from firstweek_core.db.session import session_scope
from firstweek_core.llm import LLMGateway
from firstweek_core.llm import Tier as ModelTier
from firstweek_research.extract import load_prompt, quote_in_text
from firstweek_research.retrieve import Hit, search
from firstweek_research.roles import RoleDefinition, load_roles

WRITER_VERSION = "synthesise-section.v4"
WRITER_TIER: ModelTier = "frontier"  # the report is the product, and it is written rarely
WRITER_MAX_TOKENS = 16_000  # includes thinking; the gateway doubles it if a reply is cut off
MAX_PASSAGES = 24  # per section: enough to cover a section, few enough to read closely
PER_SOURCE = 3  # passages from one source in a section, across all its searches
LEFT_OUT_BELOW = 0.10  # the plan: under 10% of postings is left out of the main report
SHOWN_IN_FULL = 15  # skills listed one per line with their interval; the rest share a line

# ---------------------------------------------------------------------- sections


@dataclass(frozen=True)
class SectionSpec:
    name: ReportSection
    title: str
    purpose: str
    tiers: tuple[Tier, ...]
    queries: tuple[str, ...] = ()  # "{role}" is replaced with the role's name
    rules: str = ""


PRACTITIONERS: tuple[Tier, ...] = ("blog", "interview", "forum")

SECTIONS: tuple[SectionSpec, ...] = (
    SectionSpec(
        "responsibilities",
        "What employers say the job involves",
        "The work job postings describe for this role: what is built and owned, how it is "
        "delivered, and who the person works with.",
        ("posting",),
        (
            "{role} responsibilities: what you will build and own",
            "design, build and ship features to production",
            "work closely with product managers, designers and engineers",
            "evaluate and improve the quality of model output",
            "own reliability, monitoring, latency and cost in production",
        ),
        "- Every passage here is a job posting: describe what employers ask for, never "
        "what the work is actually like.",
    ),
    # "A typical week" is folded in here until interviews give real time splits: blogs alone
    # gave a thin, off-topic section (ADR 0013 addendum). The contract keeps the field.
    SectionSpec(
        "day_to_day",
        "What the work is like day to day",
        "How practitioners say the work is actually done: the activities, workflows and "
        "tools of a normal working day, and how their time is split, where sources say.",
        PRACTITIONERS,
        (
            "what {role}s actually do day to day",
            "a day in the life of an AI engineer",
            "how we build and ship LLM features in practice",
            "our workflow for prompts, evaluation and deployment",
            "tools we use every day to build with LLMs",
            "how much time AI engineers spend on evaluation, debugging and meetings",
        ),
    ),
    SectionSpec(
        "pain_points",
        "The hard parts",
        "What practitioners find difficult, frustrating or unglamorous about the work.",
        PRACTITIONERS,
        (
            "the hardest parts of being a {role}",
            "frustrations of building with LLMs in production",
            "hallucinations, flaky evaluations and unreliable outputs",
            "what nobody tells you about working as an AI engineer",
            "cost, latency and debugging problems in LLM applications",
        ),
    ),
)
SUMMARY = SectionSpec(
    "summary",
    "In short",
    "Three to five sentences a reader sees first: what the job is and what the work is like. "
    "Draw only on the findings of the other sections, listed below with their passages.",
    ("posting", *PRACTITIONERS),
    rules="- Cover the job, the work and the hard parts in turn; don't introduce new points.",
)

# ---------------------------------------------------------------------- output


class CitedPassage(BaseModel):
    passage_id: uuid.UUID
    source_id: uuid.UUID
    url: str
    tier: Tier
    title: str | None
    publisher: str | None
    quote: str
    published: date | None = None  # filled in by the verifier, which reads the sources


class DraftedClaim(BaseModel):
    text: str
    citations: list[CitedPassage]
    # Set by the verifier (verify.py); None in an unverified draft.
    verification: Verification | None = None
    confidence: float | None = None
    note: str | None = None  # the verifier's reason, kept for partly supported claims


class DroppedClaim(BaseModel):
    section: ReportSection
    text: str
    reason: str
    stage: Literal["checks", "verifier"] = "checks"


class ReportDraft(BaseModel):
    """Not yet verified: the verifier labels each claim and scores its confidence."""

    role: str
    role_slug: str
    stats_version: int
    country: str
    sample_size: int
    employers: int
    date_range: tuple[date, date]
    headline: str
    asked_for: list[SkillStat]
    sections: dict[ReportSection, list[DraftedClaim]]
    not_covered: dict[ReportSection, str]
    dropped: list[DroppedClaim]
    passages_shown: dict[ReportSection, int]
    model: str
    prompt_version: str
    cost_usd: float  # everything spent on this report, the verifier included
    verifier_model: str | None = None
    verifier_prompt: str | None = None


class NoStatisticsError(LookupError):
    pass


# ---------------------------------------------------------------------- statistics


HIGH = 0.75  # the plan's confidence levels
MEDIUM = 0.5


def level(confidence: float) -> Literal["High", "Medium", "Low"]:
    if confidence >= HIGH:
        return "High"
    return "Medium" if confidence >= MEDIUM else "Low"


def latest_stats(role_slug: str) -> tuple[int, ArchetypeStats]:
    with session_scope() as session:
        row = session.execute(
            select(ArchetypeVersion.version, ArchetypeVersion.stats)
            .join(RoleArchetype, RoleArchetype.id == ArchetypeVersion.archetype_id)
            .where(RoleArchetype.slug == role_slug)
            .order_by(ArchetypeVersion.version.desc())
            .limit(1)
        ).first()
    if row is None:
        raise NoStatisticsError(
            f"No statistics for {role_slug} yet: run `make research role=...` first."
        )
    return row[0], ArchetypeStats.model_validate(row[1])


def band(share: float) -> str | None:
    """The plan's wording table: the report never says "usually" when the data says
    "sometimes"."""
    if share >= 0.60:
        return "Most roles ask for"
    if share >= 0.30:
        return "Many roles ask for"
    if share >= LEFT_OUT_BELOW:
        return "Some roles ask for"
    return None


def asked_for(stats: ArchetypeStats) -> list[SkillStat]:
    items = [s for s in [*stats.skills, *stats.tools] if s.share >= LEFT_OUT_BELOW]
    return sorted(items, key=lambda s: (-s.share, s.label))


def _month_range(start: date, end: date) -> str:
    first, last = f"{start:%b %Y}", f"{end:%b %Y}"
    return first if first == last else f"{first} to {last}"


def headline(stats: ArchetypeStats, items: list[SkillStat]) -> str:
    assert stats.date_range is not None
    sample = (
        f"Based on {stats.sample_size} {stats.country} job postings from {stats.employers} "
        f"employers, all open in the last six months (posted {_month_range(*stats.date_range)})."
    )
    groups: dict[str, list[str]] = {}
    for item in items[:12]:
        if (words := band(item.share)) is not None:
            groups.setdefault(words, []).append(f"{item.label} ({item.share:.0%})")
    asks = " ".join(f"{words} {_join(labels)}." for words, labels in groups.items())
    return f"{sample} {asks}".strip()


def _join(labels: list[str]) -> str:
    return labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " and " + labels[-1]


# ---------------------------------------------------------------------- evidence


async def gather(
    gateway: LLMGateway, role: RoleDefinition, spec: SectionSpec, *, country: str = "GB"
) -> list[Hit]:
    """The section's best passages across its searches, a few per source at most."""
    best: dict[uuid.UUID, Hit] = {}
    for query in spec.queries:
        hits = await search(
            gateway,
            query.format(role=role.name),
            role_slug=role.slug,
            country=country,
            k=10,
            tiers=spec.tiers,
        )
        for hit in hits:
            if hit.passage_id not in best or hit.score > best[hit.passage_id].score:
                best[hit.passage_id] = hit
    chosen: list[Hit] = []
    taken: dict[uuid.UUID, int] = {}
    for hit in sorted(best.values(), key=lambda h: (-h.score, str(h.passage_id))):
        if taken.get(hit.source_id, 0) < PER_SOURCE:
            chosen.append(hit)
            taken[hit.source_id] = taken.get(hit.source_id, 0) + 1
        if len(chosen) == MAX_PASSAGES:
            break
    return chosen


_TIER_NAMES: dict[str, str] = {
    "posting": "job posting",
    "blog": "blog",
    "forum": "forum",
    "interview": "interview",
}


def render_passages(labelled: dict[str, Hit]) -> str:
    blocks = []
    for label, hit in labelled.items():
        who = " · ".join(part for part in (_TIER_NAMES[hit.tier], hit.publisher, hit.title) if part)
        blocks.append(f"[{label}] {who}\n{hit.text}")
    return "\n\n".join(blocks)


# ---------------------------------------------------------------------- checks

# How often something happens comes only from the statistics.
_NEVER = re.compile(
    r"\b(most|usually|typically|generally|majority|nearly all|almost all)\b", re.IGNORECASE
)
# Fine for a pattern seen in several sources, not for one source.
# "Several workflows" counts things; "several teams" generalises across sources.
_NEEDS_TWO = re.compile(
    r"\b(often|common|commonly|frequently|widely)\b"
    r"|\b(many|several|numerous)\s+(postings?|employers?|teams?|practitioners?|writers?"
    r"|engineers?|developers?|sources?|blogs?|articles?|authors?|companies|people|roles?)\b",
    re.IGNORECASE,
)
# A number on its own: not the 4 in "Cloud4C" or the 2 in "v2".
_NUMBER = re.compile(r"(?<![\w.,])\d+(?:[.,]\d+)?(?!\w)")
# Claims are checked and dropped one by one, so one that points back at another can be left
# pointing at nothing ("The same writer ..." after the writer's first claim was dropped).
_POINTS_BACK = re.compile(
    r"^(they|he|she)\b"
    r"|\b(the same|this|these) (writer|author|engineer|team|practitioner|posting|source|blog"
    r"|article|company|employer|account|person|developer|post|newsletter)s?\b",
    re.IGNORECASE,
)


def wording_problem(text: str, sources: int, quotes: Sequence[str]) -> str | None:
    if m := _POINTS_BACK.search(text):
        return f'"{m.group(0)}" points back to another claim; each claim must stand alone'
    if m := _NEVER.search(text):
        return f'"{m.group(0)}" claims a frequency; only the statistics can say that'
    if sources < 2 and (m := _NEEDS_TWO.search(text)):
        return f'"{m.group(0)}" needs at least two sources; this claim cites one'
    quoted = " ".join(quotes)
    for number in _NUMBER.findall(text):
        if number not in quoted:
            return f"the number {number} is not in a cited quote"
    return None


def check_claims(
    section: ReportSection, draft: SectionDraft, labelled: dict[str, Hit]
) -> tuple[list[DraftedClaim], list[DroppedClaim]]:
    kept: list[DraftedClaim] = []
    dropped: list[DroppedClaim] = []
    for claim in draft.claims:
        citations: list[CitedPassage] = []
        problems: list[str] = []
        for c in claim.citations:
            hit = labelled.get(c.passage)
            if hit is None:
                problems.append(f"{c.passage} was not one of the passages")
            elif not quote_in_text(c.quote, hit.text):
                problems.append(f"the quote is not in {c.passage}")
            elif all(x.passage_id != hit.passage_id for x in citations):
                citations.append(
                    CitedPassage(
                        passage_id=hit.passage_id,
                        source_id=hit.source_id,
                        url=hit.url,
                        tier=cast(Tier, hit.tier),
                        title=hit.title,
                        publisher=hit.publisher,
                        quote=c.quote.strip(),
                    )
                )
        reason: str | None
        if not citations:
            reason = "no valid citation (" + "; ".join(problems) + ")"
        elif all(c.tier == "forum" for c in citations):
            reason = "forum posts are never the only support"
        else:
            sources = len({c.source_id for c in citations})
            reason = wording_problem(claim.text, sources, [c.quote for c in citations])
        if reason is None:
            kept.append(DraftedClaim(text=claim.text.strip(), citations=citations))
        else:
            dropped.append(DroppedClaim(section=section, text=claim.text, reason=reason))
    return kept, dropped


def drop_repeats(
    sections: dict[ReportSection, list[DraftedClaim]],
) -> list[DroppedClaim]:
    """A claim resting on a sentence an earlier claim already used says the same thing again
    (the same career-guide line once under "day to day" and once under "hard parts").
    The earlier claim stays; sections are visited in report order."""
    seen: set[str] = set()
    dropped: list[DroppedClaim] = []
    for name, claims in sections.items():
        kept: list[DraftedClaim] = []
        for claim in claims:
            keys = {" ".join(c.quote.lower().split()) for c in claim.citations}
            if keys & seen:
                dropped.append(
                    DroppedClaim(
                        section=name,
                        text=claim.text,
                        reason="repeats an earlier claim: it rests on the same quote",
                    )
                )
            else:
                seen |= keys
                kept.append(claim)
        sections[name] = kept
    return dropped


# ---------------------------------------------------------------------- writing


async def write_section(
    gateway: LLMGateway,
    role: RoleDefinition,
    spec: SectionSpec,
    labelled: dict[str, Hit],
    *,
    budget_scope: str,
    findings: str = "",
) -> tuple[SectionDraft, str]:
    system, user = load_prompt(WRITER_VERSION)
    passages = render_passages(labelled)
    if findings:
        passages = f"Findings of the other sections:\n{findings}\n\n{passages}"
    result = await gateway.structured(
        purpose=f"write-report-{spec.name}",
        messages=[
            {"role": "system", "content": system.format(section_rules=spec.rules)},
            {
                "role": "user",
                "content": user.format(
                    role_name=role.name,
                    role_definition=role.definition,
                    section_title=spec.title,
                    section_purpose=spec.purpose,
                    passages=passages,
                ),
            },
        ],
        response_model=SectionDraft,
        tier=WRITER_TIER,
        max_tokens=WRITER_MAX_TOKENS,
        budget_scope=budget_scope,
        prompt_version=WRITER_VERSION,
    )
    assert result.parsed is not None
    return result.parsed, result.model


def _label(hits: Sequence[Hit]) -> dict[str, Hit]:
    return {f"P{i}": hit for i, hit in enumerate(hits, 1)}


async def draft_report(
    gateway: LLMGateway,
    role_slug: str,
    *,
    budget_usd: float = 1.5,
    progress: Callable[[str], None] | None = None,
) -> ReportDraft:
    report = progress or (lambda _: None)
    role = load_roles()[role_slug]
    version, stats = latest_stats(role_slug)
    if stats.date_range is None or stats.sample_size == 0:
        raise NoStatisticsError(f"The latest statistics for {role.name} have no postings.")
    scope = f"report:{role_slug}:{uuid.uuid4().hex[:8]}"
    gateway.budget(scope, Decimal(str(budget_usd)))
    items = asked_for(stats)

    report(f"Finding evidence for {len(SECTIONS)} sections...")
    evidence = [
        _label(await gather(gateway, role, spec, country=stats.country)) for spec in SECTIONS
    ]
    report(
        "Writing sections with "
        f"{gateway.model_for(WRITER_TIER)}: "
        + ", ".join(
            f"{s.name} ({len(e)} passages)" for s, e in zip(SECTIONS, evidence, strict=True)
        )
    )
    written = await asyncio.gather(
        *[
            write_section(gateway, role, spec, labelled, budget_scope=scope)
            for spec, labelled in zip(SECTIONS, evidence, strict=True)
            if labelled
        ]
    )
    drafts = iter(written)
    sections: dict[ReportSection, list[DraftedClaim]] = {}
    not_covered: dict[ReportSection, str] = {}
    dropped: list[DroppedClaim] = []
    shown: dict[ReportSection, int] = {}
    model = gateway.model_for(WRITER_TIER)
    for spec, labelled in zip(SECTIONS, evidence, strict=True):
        shown[spec.name] = len(labelled)
        if not labelled:
            sections[spec.name] = []
            not_covered[spec.name] = "No evidence collected for this section yet."
            continue
        draft, model = next(drafts)
        sections[spec.name], lost = check_claims(spec.name, draft, labelled)
        dropped += lost
        if draft.not_covered:
            not_covered[spec.name] = draft.not_covered
    dropped += drop_repeats(sections)

    # The summary sees only what survived the checks, with those claims' own passages.
    cited: dict[uuid.UUID, Hit] = {}
    findings: list[str] = []
    for spec, labelled in zip(SECTIONS, evidence, strict=True):
        by_id = {h.passage_id: h for h in labelled.values()}
        for claim in sections[spec.name]:
            for c in claim.citations:
                cited.setdefault(c.passage_id, by_id[c.passage_id])
    summary_passages = _label(list(cited.values()))
    label_of = {hit.passage_id: label for label, hit in summary_passages.items()}
    for spec in SECTIONS:
        for claim in sections[spec.name]:
            refs = ", ".join(label_of[c.passage_id] for c in claim.citations)
            findings.append(f"- ({spec.title}) {claim.text} [{refs}]")
    shown["summary"] = len(summary_passages)
    if summary_passages:
        report("Writing the summary from the checked findings...")
        draft, model = await write_section(
            gateway,
            role,
            SUMMARY,
            summary_passages,
            budget_scope=scope,
            findings="\n".join(findings),
        )
        sections["summary"], lost = check_claims("summary", draft, summary_passages)
        dropped += lost
        if draft.not_covered:
            not_covered["summary"] = draft.not_covered
    else:
        sections["summary"] = []
        not_covered["summary"] = "Nothing in the other sections survived the checks."

    return ReportDraft(
        role=role.name,
        role_slug=role.slug,
        stats_version=version,
        country=stats.country,
        sample_size=stats.sample_size,
        employers=stats.employers,
        date_range=stats.date_range,
        headline=headline(stats, items),
        asked_for=items,
        sections=sections,
        not_covered=not_covered,
        dropped=dropped,
        passages_shown=shown,
        model=model,
        prompt_version=WRITER_VERSION,
        cost_usd=float(gateway.budget(scope).spent_usd),
    )


# ---------------------------------------------------------------------- reading


def asked_for_lines(items: Sequence[SkillStat]) -> list[str]:
    """The top skills one per line with their interval (ties with the last one included, so
    equal shares are never split), then the rest on one line per band."""
    full = list(items[:SHOWN_IN_FULL])
    rest = list(items[SHOWN_IN_FULL:])
    while full and rest and rest[0].share == full[-1].share:
        full.append(rest.pop(0))
    lines = [
        f"- {band(s.share)} {s.label}: {s.share:.0%} of {s.n} postings "
        f"(95% interval {s.ci_low:.0%} to {s.ci_high:.0%})"
        for s in full
    ]
    groups: dict[str, list[str]] = {}
    for s in rest:
        if (words := band(s.share)) is not None:
            groups.setdefault(words, []).append(f"{s.label} ({s.share:.0%})")
    lines += [
        f"- {words.replace(' ask for', ' also ask for')}: {', '.join(labels)}"
        for words, labels in groups.items()
    ]
    return lines


def to_markdown(draft: ReportDraft) -> str:
    """For review in a terminal or an editor: claims, numbered sources and what was cut."""
    verified = draft.verifier_model is not None
    state = "verified, not yet reviewed" if verified else "draft, not yet verified"
    lines = [f"# {draft.role}: Role Reality Report ({state})", "", draft.headline, ""]
    if verified:
        lines += [
            "_Each claim shows its confidence: High is 0.75 or more, Medium 0.5 to 0.75, "
            "Low under 0.5. Low claims are hidden or flagged in the product._",
            "",
        ]
    numbers: dict[uuid.UUID, int] = {}
    sources: list[CitedPassage] = []

    def refs(claim: DraftedClaim) -> str:
        """One number per source, in order: two passages of one posting are one source."""
        for c in claim.citations:
            if c.source_id not in numbers:
                numbers[c.source_id] = len(numbers) + 1
                sources.append(c)
        return "".join(f"[{n}]" for n in sorted({numbers[c.source_id] for c in claim.citations}))

    def badge(claim: DraftedClaim) -> str:
        if claim.confidence is None:
            return ""
        partly = f" · partly supported: _{claim.note}_" if claim.verification == "partial" else ""
        return f" · **{level(claim.confidence)}** {claim.confidence:.2f}{partly}"

    def section(name: ReportSection, title: str) -> None:
        lines.extend([f"## {title}", ""])
        lines.extend(f"- {c.text} {refs(c)}{badge(c)}" for c in draft.sections.get(name, []))
        if name in draft.not_covered:
            lines.append(f"- _Not covered: {draft.not_covered[name]}_")
        lines.append("")

    section("summary", SUMMARY.title)
    lines.extend(["## What employers ask for", ""])
    lines.extend(asked_for_lines(draft.asked_for))
    lines.append("")
    for spec in SECTIONS:
        section(spec.name, spec.title)
    lines += ["## Sources", ""]
    for i, c in enumerate(sources, 1):
        who = " · ".join(p for p in (_TIER_NAMES[c.tier], c.publisher, c.title) if p)
        lines.append(f"{i}. {who}: {c.url}")
    for stage, heading in (
        ("checks", "Left out by the checks"),
        ("verifier", "Removed by the verifier"),
    ):
        gone = [d for d in draft.dropped if d.stage == stage]
        if gone:
            lines += ["", f"## {heading}", ""]
            lines += [f"- ({d.section}) {d.text} **Why:** {d.reason}" for d in gone]
    checked = (
        f" Checked by {draft.verifier_model} with {draft.verifier_prompt}." if verified else ""
    )
    lines += [
        "",
        f"_Statistics version {draft.stats_version}. Written by {draft.model} with "
        f"{draft.prompt_version}.{checked} Cost ${draft.cost_usd:.2f}._",
    ]
    return "\n".join(lines) + "\n"
