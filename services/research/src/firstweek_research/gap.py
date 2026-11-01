"""Skill gap: how a person's own background lines up with the skills a role asks for (ADR 0016).

The skills and their shares come from the stored report (collected evidence). The model
only judges the match between those skills and the background text, and code keeps a 'have'
or 'transferable' only when the words it quotes are really in the background."""

import uuid
from dataclasses import dataclass

from sqlalchemy import select

from firstweek_core.contracts import GapDraftItem, GapItem, GapReply, SkillStat
from firstweek_core.db.models import RoleReport
from firstweek_core.db.session import session_scope
from firstweek_core.llm import LLMGateway
from firstweek_core.llm import Tier as ModelTier
from firstweek_research.extract import load_prompt, quote_in_text

GAP_VERSION = "skill-gap.v1"
GAP_TIER: ModelTier = "mid"
MIN_SHARE = 0.20  # skills under 20% of postings are not worth a gap line
MAX_SKILLS = 25
MAX_BACKGROUND_CHARS = 3000
CREDIT = {"have": 1.0, "transferable": 0.5, "missing": 0.0}


class GapError(Exception):
    """Something the caller can fix: no stored report, or an empty background."""


@dataclass(frozen=True)
class SkillGap:
    items: list[GapItem]
    shares: dict[str, float]  # skill_id -> share of postings asking for it
    labels: dict[str, str]
    model: str
    cost_usd: float

    @property
    def coverage(self) -> float:
        """Share-weighted: a skill most postings ask for counts more. Transferable counts half."""
        total = sum(self.shares.values())
        have = sum(self.shares[i.skill_id] * CREDIT[i.status] for i in self.items)
        return have / total if total else 0.0


def select_skills(stats: list[SkillStat]) -> list[SkillStat]:
    """The skills worth a gap line: asked for by at least MIN_SHARE of postings, most first."""
    chosen = [s for s in stats if s.share >= MIN_SHARE]
    return sorted(chosen, key=lambda s: -s.share)[:MAX_SKILLS]


def asked_skills(report_id: uuid.UUID | None = None, *, slug: str | None = None) -> list[SkillStat]:
    """The skills a stored report says the role asks for, most asked first."""
    with session_scope() as session:
        query = select(RoleReport)
        if report_id is not None:
            query = query.where(RoleReport.id == report_id)
        else:
            from firstweek_core.db.models import ArchetypeVersion, RoleArchetype

            query = (
                query.join(ArchetypeVersion, ArchetypeVersion.id == RoleReport.archetype_version_id)
                .join(RoleArchetype, RoleArchetype.id == ArchetypeVersion.archetype_id)
                .where(RoleArchetype.slug == slug)
            )
        row = session.execute(query.order_by(RoleReport.created_at.desc()).limit(1)).scalar()
        if row is None:
            raise GapError("No stored report for this role. Run `make report` first.")
        stats = [SkillStat.model_validate(s) for s in row.report.get("asked_for") or []]
    return select_skills(stats)


def check_items(
    drafts: list[GapDraftItem], skills: list[SkillStat], background: str
) -> list[GapItem]:
    """One item per skill, in the skills' order. Unknown ids and repeats are ignored; a skill
    the model skipped, or claimed without words from the background, is missing."""
    by_id = {s.skill_id: s for s in skills}
    first: dict[str, GapDraftItem] = {}
    for item in drafts:
        if item.skill_id in by_id:
            first.setdefault(item.skill_id, item)
    items: list[GapItem] = []
    for skill in skills:
        d = first.get(skill.skill_id)
        if d is None:
            items.append(GapItem(skill_id=skill.skill_id, status="missing", reason="Not assessed."))
        elif d.status != "missing" and not (
            d.background_quote and quote_in_text(d.background_quote, background)
        ):
            items.append(
                GapItem(
                    skill_id=skill.skill_id,
                    status="missing",
                    reason="Nothing in your background says this.",
                )
            )
        elif d.status == "missing":
            items.append(GapItem(skill_id=skill.skill_id, status="missing", reason=d.reason))
        else:
            reason = f'{d.reason.rstrip(".")} (you wrote: "{d.background_quote}").'
            items.append(GapItem(skill_id=skill.skill_id, status=d.status, reason=reason))
    return items


async def skill_gap(
    gateway: LLMGateway,
    role_name: str,
    skills: list[SkillStat],
    background: str,
    *,
    budget_usd: float = 0.25,
) -> SkillGap:
    background = background.strip()
    if not background:
        raise GapError("Write a few lines about your background first.")
    if not skills:
        raise GapError("The stored report lists no skills asked for by 20% of postings or more.")
    background = background[:MAX_BACKGROUND_CHARS]
    system, user = load_prompt(GAP_VERSION)
    listing = "\n".join(f"- {s.skill_id} | {s.label} | {s.share:.0%}" for s in skills)
    result = await gateway.structured(
        purpose="skill-gap",
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": user.format(role_name=role_name, skills=listing, background=background),
            },
        ],
        response_model=GapReply,
        tier=GAP_TIER,
        max_tokens=3000,
        temperature=0.0,
        budget_scope="skill-gap",
        budget_usd=budget_usd,
        prompt_version=GAP_VERSION,
    )
    assert result.parsed is not None
    return SkillGap(
        items=check_items(result.parsed.items, skills, background),
        shares={s.skill_id: s.share for s in skills},
        labels={s.skill_id: s.label for s in skills},
        model=result.model,
        cost_usd=float(result.cost_usd),
    )


def to_text(gap: SkillGap, role_name: str) -> str:
    """The gap as a reader sees it: what you have, what carries over, what is missing."""
    names = {"have": "You have", "transferable": "Close to what you have", "missing": "Missing"}
    lines = [f"# Your skill gap for {role_name}", ""]
    for status in ("have", "transferable", "missing"):
        group = [i for i in gap.items if i.status == status]
        lines.append(f"## {names[status]} ({len(group)})")
        for i in group:
            lines.append(
                f"- {gap.labels[i.skill_id]} (asked by {gap.shares[i.skill_id]:.0%} of postings): "
                f"{i.reason}"
            )
        lines.append("")
    lines.append(
        f"Weighted by how often postings ask for each skill, your background covers "
        f"{gap.coverage:.0%} (a close match counts half)."
    )
    lines.append(
        "_The matching is the model's judgement of your own words; the skills and shares come "
        "from the collected postings._"
    )
    return "\n".join(lines)
