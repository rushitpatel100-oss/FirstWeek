"""Turn stored matches and extractions into statistics for one role.

The sample is: postings in the country, not duplicates, full text (never snippets),
judged to be the role with confidence >= 0.5, and extracted with the current extractor.
An employer advertising the same title more than once counts once: reposts and
per-location copies with small wording changes would otherwise weigh that employer's
template more than everyone else's.
"""

import math
import re
import statistics
import unicodedata
import uuid
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import ColumnElement, and_, func, select
from sqlalchemy.orm import Session

from firstweek_core.contracts import ArchetypeStats, SalaryStat, SkillStat
from firstweek_core.db.models import (
    ArchetypeVersion,
    Extraction,
    ExtractionRun,
    JobPosting,
    PostingRoleMatch,
    TaxonomySkill,
)
from firstweek_research.extract import CLASSIFIER_VERSION, EXTRACTOR_VERSION
from firstweek_research.roles import RoleDefinition, resolve_role
from firstweek_research.taxonomy import load_taxonomy

MATCH_CONFIDENCE = 0.5
# Statistics cover postings seen open at some point in this many days before the run.
# Daily collection keeps adding postings, so the sample grows while staying current.
WINDOW_DAYS = 183
MIN_SALARY_POSTINGS = 3
MAX_LISTED = 40


def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a proportion k/n. Sensible even for tiny samples."""
    if n == 0:
        return 0.0, 1.0
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def _skill_stats(counts: Counter[str], n: int, kind: str) -> list[SkillStat]:
    taxonomy = load_taxonomy()
    rows = []
    for slug, k in counts.most_common():
        if taxonomy.entries[slug].kind != kind:
            continue
        low, high = wilson_interval(k, n)
        share = k / n
        rows.append(
            SkillStat(
                skill_id=slug,
                label=taxonomy.entries[slug].label,
                count=k,
                share=round(share, 4),
                ci_low=round(min(low, share), 4),
                ci_high=round(max(high, share), 4),
                n=n,
            )
        )
    return rows[:MAX_LISTED]


def _salaries(rows: list[tuple[Decimal | None, Decimal | None, str | None]]) -> list[SalaryStat]:
    by_currency: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for low, high, currency in rows:
        if currency and low is not None and high is not None:
            by_currency[currency].append((float(low), float(high)))
    return [
        SalaryStat(
            currency=currency,
            postings=len(pairs),
            median_min=statistics.median(p[0] for p in pairs),
            median_max=statistics.median(p[1] for p in pairs),
        )
        for currency, pairs in sorted(by_currency.items(), key=lambda kv: -len(kv[1]))
        if len(pairs) >= MIN_SALARY_POSTINGS
    ]


def _title_key(title: str) -> str:
    """Ignores case, punctuation and spacing only. Seniority and team stay significant:
    "Senior" and "Principal" at one employer are different jobs."""
    text = unicodedata.normalize("NFKC", title).casefold()
    return " ".join(re.sub(r"[^\w]+", " ", text).split())


def window_start(as_of: datetime | None = None, window_days: int = WINDOW_DAYS) -> datetime:
    return (as_of or datetime.now(UTC)) - timedelta(days=window_days)


def current_match(role: RoleDefinition) -> ColumnElement[bool]:
    """Decisions made by the current classifier against the role's current definition."""
    return and_(
        PostingRoleMatch.classifier_version == CLASSIFIER_VERSION,
        PostingRoleMatch.definition_hash == role.definition_hash,
    )


def one_per_employer_title(postings: list[JobPosting]) -> list[JobPosting]:
    """Keeps the most recent posting for each (employer, title)."""
    best: dict[tuple[str, str], JobPosting] = {}
    ordered = sorted(postings, key=lambda p: (p.posted_at or date.min, str(p.id)), reverse=True)
    for p in ordered:
        best.setdefault(((p.company or "").casefold(), _title_key(p.title)), p)
    return sorted(best.values(), key=lambda p: str(p.id))


def compute_stats(
    session: Session,
    role: RoleDefinition,
    archetype_id: uuid.UUID,
    country: str,
    *,
    as_of: datetime | None = None,
    window_days: int = WINDOW_DAYS,
) -> ArchetypeStats:
    since = window_start(as_of, window_days)
    matched = (
        session.execute(
            select(JobPosting)
            .join(PostingRoleMatch, PostingRoleMatch.posting_id == JobPosting.id)
            .join(ExtractionRun, ExtractionRun.source_id == JobPosting.source_id)
            .where(
                JobPosting.country == country,
                JobPosting.last_seen_at >= since,
                JobPosting.is_duplicate.is_(False),
                JobPosting.is_full_text.is_(True),
                PostingRoleMatch.archetype_id == archetype_id,
                current_match(role),
                PostingRoleMatch.is_match.is_(True),
                PostingRoleMatch.confidence >= MATCH_CONFIDENCE,
                ExtractionRun.extractor_version == EXTRACTOR_VERSION,
            )
        )
        .scalars()
        .all()
    )
    sample = one_per_employer_title(list(matched))
    n = len(sample)
    source_ids = [p.source_id for p in sample]

    mentions = session.execute(
        select(
            Extraction.source_id, Extraction.skill_id, Extraction.kind, Extraction.raw_text
        ).where(
            Extraction.source_id.in_(source_ids),
            Extraction.extractor_version == EXTRACTOR_VERSION,
            Extraction.kind.in_(["skill", "tool"]),
        )
    ).all()
    slug_of = {
        row.id: row.slug for row in session.execute(select(TaxonomySkill.id, TaxonomySkill.slug))
    }
    per_posting: Counter[str] = Counter()
    for _source_id, slug in {(m.source_id, slug_of[m.skill_id]) for m in mentions if m.skill_id}:
        per_posting[slug] += 1
    unmapped = {m.raw_text.casefold() for m in mentions if m.skill_id is None}

    dropped = session.scalar(
        select(func.coalesce(func.sum(ExtractionRun.items_dropped), 0)).where(
            ExtractionRun.source_id.in_(source_ids),
            ExtractionRun.extractor_version == EXTRACTOR_VERSION,
        )
    )
    snippets = session.execute(
        select(
            JobPosting.title,
            JobPosting.salary_min,
            JobPosting.salary_max,
            JobPosting.salary_currency,
        ).where(
            JobPosting.country == country,
            JobPosting.last_seen_at >= since,
            JobPosting.is_full_text.is_(False),
            JobPosting.is_duplicate.is_(False),
        )
    ).all()
    role_snippets = [s for s in snippets if resolve_role(s.title).slug == role.slug]

    dates = [p.posted_at for p in sample if p.posted_at]
    date_range: tuple[date, date] | None = (min(dates), max(dates)) if dates else None
    return ArchetypeStats(
        role=role.name,
        country=country,
        sample_size=n,
        repeat_postings_merged=len(matched) - n,
        employers=len({p.company for p in sample if p.company}),
        date_range=date_range,
        sources=dict(Counter(p.provider for p in sample)),
        skills=_skill_stats(per_posting, n, "skill") if n else [],
        tools=_skill_stats(per_posting, n, "tool") if n else [],
        seniority=dict(Counter(p.seniority or "unclear" for p in sample)),
        salary=_salaries(
            [(p.salary_min, p.salary_max, p.salary_currency) for p in sample]
            + [(s.salary_min, s.salary_max, s.salary_currency) for s in role_snippets]
        ),
        demand_snippets=len(role_snippets),
        unverified_items_dropped=int(dropped or 0),
        unmapped_terms=len(unmapped),
        classifier_version=CLASSIFIER_VERSION,
        extractor_version=EXTRACTOR_VERSION,
        definition_hash=role.definition_hash,
        window_days=window_days,
    )


def save_version(
    session: Session, archetype_id: uuid.UUID, stats: ArchetypeStats
) -> ArchetypeVersion | None:
    """Store a draft version. Nothing is stored for an empty sample."""
    if stats.sample_size == 0 or stats.date_range is None:
        return None
    latest = session.scalar(
        select(func.max(ArchetypeVersion.version)).where(
            ArchetypeVersion.archetype_id == archetype_id
        )
    )
    version = ArchetypeVersion(
        archetype_id=archetype_id,
        version=(latest or 0) + 1,
        country=stats.country,
        date_from=stats.date_range[0],
        date_to=stats.date_range[1],
        sample_size=stats.sample_size,
        stats=stats.model_dump(mode="json"),
        status="draft",
    )
    session.add(version)
    session.flush()
    return version
