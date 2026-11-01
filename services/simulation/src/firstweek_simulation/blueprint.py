"""Blueprint design: a fictional company, tickets and rubric from a role's pain points (ADR 0018).

The model proposes; code checks. A blueprint is only kept if its pain points exist, its task
types fit the role, its skills are ones postings ask for, and the rubric covers every skill a
ticket assesses. One repair attempt is made with the problems listed; after that the caller
sees the problems. The answer key is a placeholder until the reference solution exists."""

import re
import uuid
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Any

import yaml
from sqlalchemy import select

from firstweek_core.contracts import (
    AnswerKey,
    BlueprintDraft,
    Criterion,
    ProjectBlueprint,
    RoleRealityReport,
    SkillStat,
    Ticket,
)
from firstweek_core.db.models import ArchetypeVersion, Blueprint, RoleArchetype, RoleReport
from firstweek_core.db.session import session_scope
from firstweek_core.llm import LLMGateway
from firstweek_core.llm import Tier as ModelTier

BLUEPRINT_VERSION = "design-blueprint.v1"
BLUEPRINT_TIER: ModelTier = "mid"
MIN_SHARE = 0.10  # skills under 10% of postings are not worth assessing
MAX_SKILLS = 30
MIN_DAYS = 3
MIN_WEIGHT = 0.05
PENDING_SOLUTION = "pending:reference-solution"


@cache
def load_prompt(version: str) -> tuple[str, str]:
    """Returns (system, user template) from prompts/<version>.md."""
    path = resources.files("firstweek_simulation") / "prompts" / f"{version}.md"
    system, user = path.read_text("utf-8").split("=== user ===")
    return system.strip(), user.strip()


class BlueprintError(Exception):
    """Something the caller can fix: no stored report, or a design that stays invalid."""


@dataclass(frozen=True)
class TaskLibrary:
    summaries: dict[str, str]
    checkable: set[str]
    by_role: dict[str, list[str]]
    default: list[str]

    def allowed(self, slug: str) -> list[str]:
        return self.by_role.get(slug, self.default)


def load_task_library() -> TaskLibrary:
    path = resources.files("firstweek_simulation") / "data" / "task_types.yaml"
    raw: dict[str, Any] = yaml.safe_load(path.read_text("utf-8"))
    types: dict[str, dict[str, Any]] = raw["types"]
    library = TaskLibrary(
        summaries={k: str(v["summary"]) for k, v in types.items()},
        checkable={k for k, v in types.items() if v["checkable"]},
        by_role={k: list(v) for k, v in raw["roles"].items()},
        default=list(raw["default"]),
    )
    for slug, allowed in [*library.by_role.items(), ("default", library.default)]:
        unknown = set(allowed) - set(library.summaries)
        if unknown:
            raise ValueError(f"{slug} allows unknown task types: {sorted(unknown)}")
    return library


@dataclass(frozen=True)
class Findings:
    """What the design is built from: the stored report's own words and numbers."""

    version_id: uuid.UUID
    role_name: str
    pain_points: list[str]
    responsibilities: list[str]
    skills: list[SkillStat]


def select_skills(stats: list[SkillStat]) -> list[SkillStat]:
    chosen = [s for s in stats if s.share >= MIN_SHARE]
    return sorted(chosen, key=lambda s: -s.share)[:MAX_SKILLS]


def load_findings(slug: str) -> Findings:
    """The latest stored report for a role. Rejected claims are already gone from it."""
    with session_scope() as session:
        row = session.execute(
            select(RoleReport, RoleArchetype.name)
            .join(ArchetypeVersion, ArchetypeVersion.id == RoleReport.archetype_version_id)
            .join(RoleArchetype, RoleArchetype.id == ArchetypeVersion.archetype_id)
            .where(RoleArchetype.slug == slug)
            .order_by(RoleReport.created_at.desc())
            .limit(1)
        ).first()
        if row is None:
            raise BlueprintError("No stored report for this role. Run `make report` first.")
        report = RoleRealityReport.model_validate(row[0].report)
        version_id, name = row[0].archetype_version_id, row[1]
    if not report.pain_points:
        raise BlueprintError("The stored report has no pain points to build a scenario on.")
    skills = select_skills(report.asked_for)
    if not skills:
        raise BlueprintError("The stored report lists no skills asked for by 10% of postings.")
    return Findings(
        version_id=version_id,
        role_name=name,
        pain_points=[c.text for c in report.pain_points],
        responsibilities=[c.text for c in report.responsibilities[:6]],
        skills=skills,
    )


def ticket_prefix(role_name: str) -> str:
    """GenAI Engineer -> GENAI; Agentic AI Engineer -> AGENTIC."""
    first = re.sub(r"[^A-Za-z0-9]", "", role_name.split()[0]).upper()
    return first if first and first[0].isalpha() and len(first) >= 2 else "SIM"


def problems_with(
    draft: BlueprintDraft, findings: Findings, allowed: list[str], library: TaskLibrary
) -> list[str]:
    """Everything wrong with a draft, as sentences the model can act on."""
    problems: list[str] = []
    n = len(findings.pain_points)
    bad = [i for i in draft.grounded_in if not 1 <= i <= n]
    if bad or len(set(draft.grounded_in)) != len(draft.grounded_in):
        problems.append(f"grounded_in must be distinct pain point numbers from 1 to {n}.")
    known = {s.skill_id for s in findings.skills}
    for t in draft.tickets:
        if t.task_type not in allowed:
            problems.append(f"'{t.title}' uses task type {t.task_type}; allowed: {allowed}.")
        if unknown := sorted(set(t.skills) - known):
            problems.append(f"'{t.title}' assesses unknown skills {unknown}; use listed ids.")
    if len({t.due_day for t in draft.tickets}) < MIN_DAYS:
        problems.append(f"Tickets must fall on at least {MIN_DAYS} different days.")
    if not any(t.task_type in library.checkable and t.task_type == "code" for t in draft.tickets):
        problems.append("At least one ticket must be a code ticket that tests can check.")
    rubric_ids = [c.skill_id for c in draft.rubric]
    if len(set(rubric_ids)) != len(rubric_ids):
        problems.append("Each skill appears once in the rubric.")
    if unknown := sorted(set(rubric_ids) - known):
        problems.append(f"The rubric uses unknown skills {unknown}; use listed ids.")
    ticket_skills = {s for t in draft.tickets for s in t.skills}
    if missing := sorted(ticket_skills - set(rubric_ids)):
        problems.append(f"Tickets assess skills missing from the rubric: {missing}.")
    if unused := sorted(set(rubric_ids) - ticket_skills):
        problems.append(f"Rubric skills no ticket assesses: {unused}.")
    for c in draft.rubric:
        if set(c.anchors) != {1, 2, 3, 4, 5}:
            problems.append(f"Rubric criterion {c.skill_id} needs anchors for scores 1 to 5.")
    return problems


def scale_weights(weights: list[float]) -> list[float]:
    """Relative weights scaled to sum to 1, none under MIN_WEIGHT, rounded to two places."""
    total = sum(weights)
    scaled = [max(MIN_WEIGHT, w / total) for w in weights]
    again = sum(scaled)
    scaled = [round(w / again, 2) for w in scaled]
    scaled[scaled.index(max(scaled))] += round(1.0 - sum(scaled), 2)  # rounding leftovers
    return scaled


def build_blueprint(draft: BlueprintDraft, findings: Findings) -> ProjectBlueprint:
    """A checked draft as a blueprint. Tickets are numbered from 101 in due-day order."""
    prefix = ticket_prefix(findings.role_name)
    ordered = sorted(draft.tickets, key=lambda t: t.due_day)
    tickets = [
        Ticket(
            key=f"{prefix}-{101 + i}",
            title=t.title,
            description=t.description,
            acceptance_criteria=t.acceptance_criteria,
            task_type=t.task_type,
            due_day=t.due_day,
            skills=t.skills,
        )
        for i, t in enumerate(ordered)
    ]
    weights = scale_weights([c.weight for c in draft.rubric])
    rubric = [
        Criterion(skill_id=c.skill_id, weight=w, anchors=c.anchors, checks=c.checks)
        for c, w in zip(draft.rubric, weights, strict=True)
    ]
    return ProjectBlueprint(
        archetype=findings.role_name,
        scenario=f"{draft.company_name}: {draft.scenario}",
        company_context=draft.company_context,
        tickets=tickets,
        rubric=rubric,
        answer_key=AnswerKey(
            reference_solution_uri=PENDING_SOLUTION,
            planted_issues=draft.planted_issues,
            expected_metrics=draft.expected_metrics,
        ),
    )


@dataclass(frozen=True)
class DesignedBlueprint:
    blueprint: ProjectBlueprint
    grounded_in: list[str]  # the pain point texts the scenario rests on
    attempts: int
    model: str
    cost_usd: float


async def design_blueprint(
    gateway: LLMGateway,
    slug: str,
    findings: Findings,
    *,
    library: TaskLibrary | None = None,
    budget_usd: float = 1.0,
) -> DesignedBlueprint:
    library = library or load_task_library()
    allowed = library.allowed(slug)
    system, user = load_prompt(BLUEPRINT_VERSION)
    task_types = "\n".join(f"- {t}: {library.summaries[t]}" for t in allowed)
    pain = "\n".join(f"{i}. {text}" for i, text in enumerate(findings.pain_points, 1))
    work = "\n".join(f"- {text}" for text in findings.responsibilities) or "(none recorded)"
    skills = "\n".join(f"- {s.skill_id} | {s.label} | {s.share:.0%}" for s in findings.skills)
    problems: list[str] = []
    cost, model = 0.0, ""
    for attempt in (1, 2):
        result = await gateway.structured(
            purpose="design-blueprint",
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": user.format(
                        role_name=findings.role_name,
                        task_types=task_types,
                        pain_points=pain,
                        responsibilities=work,
                        skills=skills,
                        problems="\n".join(f"- {p}" for p in problems) or "(none)",
                    ),
                },
            ],
            response_model=BlueprintDraft,
            tier=BLUEPRINT_TIER,
            max_tokens=6000,
            temperature=0.7,
            budget_scope="design-blueprint",
            budget_usd=budget_usd,
            prompt_version=BLUEPRINT_VERSION,
        )
        assert result.parsed is not None
        cost += float(result.cost_usd)
        model = result.model
        problems = problems_with(result.parsed, findings, allowed, library)
        if not problems:
            return DesignedBlueprint(
                blueprint=build_blueprint(result.parsed, findings),
                grounded_in=[findings.pain_points[i - 1] for i in result.parsed.grounded_in],
                attempts=attempt,
                model=model,
                cost_usd=cost,
            )
    raise BlueprintError(
        "The design stayed invalid after a repair attempt:\n- " + "\n- ".join(problems)
    )


def store_blueprint(findings: Findings, designed: DesignedBlueprint) -> uuid.UUID:
    """Saves a draft: the public view in `blueprint`, the answer key apart. Not validated yet."""
    bp = designed.blueprint
    with session_scope() as session:
        row = Blueprint(
            archetype_version_id=findings.version_id,
            scenario=bp.scenario,
            blueprint=bp.public_view(),
            answer_key=bp.answer_key.model_dump(),
            validated=False,
            status="draft",
        )
        session.add(row)
        session.flush()
        return row.id


def to_text(designed: DesignedBlueprint) -> str:
    """The blueprint as a reviewer reads it, answer key included (never shown to agents)."""
    bp = designed.blueprint
    lines = [f"# Blueprint: {bp.archetype}", "", f"## Scenario\n{bp.scenario}", ""]
    lines += [f"## Company\n{bp.company_context}", "", "## Built on these pain points"]
    lines += [f"- {text}" for text in designed.grounded_in]
    lines += ["", "## Tickets"]
    for t in bp.tickets:
        lines.append(
            f"- {t.key} (day {t.due_day}, {t.task_type}): {t.title}  [{', '.join(t.skills)}]"
        )
        lines += [f"    - {c}" for c in t.acceptance_criteria]
    lines += ["", "## Rubric"]
    for c in bp.rubric:
        lines.append(f"- {c.skill_id} ({c.weight:.0%}): checks: {'; '.join(c.checks)}")
    lines += ["", "## Answer key (hidden from colleagues)"]
    lines += [f"- {issue}" for issue in bp.answer_key.planted_issues]
    if bp.answer_key.expected_metrics:
        lines.append(f"- expected metrics: {bp.answer_key.expected_metrics}")
    lines += [
        "",
        f"_Attempts: {designed.attempts}. Model: {designed.model}. Cost: ${designed.cost_usd:.2f}. "
        "The reference solution does not exist yet; the validation gate comes next._",
    ]
    return "\n".join(lines)
