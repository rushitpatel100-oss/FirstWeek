"""Design, build and gate a project unattended (ADR 0020).

The gate is the product's quality control: a blueprint is approved only if its starter runs and
fails the target tests, its reference solution passes them, and the reference's measured numbers
exist. A failed build is retried up to `attempts` times with the failures written into the
planner's prompt. Approval here is automatic and labelled as such; nothing a person looked at."""

import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select

from firstweek_core.contracts import Internship, RoleRealityReport
from firstweek_core.db.models import ArchetypeVersion, Blueprint, RoleArchetype, RoleReport
from firstweek_core.db.session import session_scope
from firstweek_core.llm import LLMGateway
from firstweek_core.llm import Tier as ModelTier
from firstweek_core.sandbox import SandboxRunner
from firstweek_simulation.artifacts import (
    SHARED_SEED,
    BuiltArtifacts,
    Check,
    save_artifacts,
    to_text,
)
from firstweek_simulation.artifacts import build_artifacts as build
from firstweek_simulation.blueprint import (
    BlueprintError,
    DesignedBlueprint,
    Findings,
    design_blueprint,
    findings_from_report,
    store_blueprint,
)
from firstweek_simulation.blueprint import to_text as blueprint_text
from firstweek_simulation.internship import write_internship
from firstweek_simulation.week import design_week

MAX_ATTEMPTS = 3


@dataclass
class PipelineResult:
    designed: DesignedBlueprint
    built: BuiltArtifacts
    attempts: int
    history: list[list[Check]] = field(default_factory=list)  # every attempt's checks
    cost_usd: float = 0.0
    week: Internship | None = None  # the scripted week, when one could be written

    @property
    def approved(self) -> bool:
        return self.built.ok and bool(self.built.metrics)


def failures_text(built: BuiltArtifacts) -> str:
    """What went wrong, as the planner needs to read it."""
    lines = [f"- {c.name}: {c.detail or 'failed'}" for c in built.checks if not c.ok]
    return "\n".join(lines) or "- the metrics script reported no numbers"


async def run_pipeline(
    gateway: LLMGateway,
    runner: SandboxRunner,
    slug: str,
    findings: Findings,
    *,
    tier: ModelTier = "judge",
    attempts: int = MAX_ATTEMPTS,
    seed: int = SHARED_SEED,
    budget_usd: float = 1.0,
    progress: Callable[[str], None] = lambda _: None,
) -> PipelineResult:
    progress(f"Designing the blueprint for {findings.role_name} ({tier} tier) ...")
    designed = await design_blueprint(gateway, slug, findings, tier=tier, budget_usd=budget_usd)
    progress(
        f"Blueprint ready: {len(designed.blueprint.tickets)} tickets. Building the project ..."
    )
    result: PipelineResult | None = None
    feedback = ""
    cost = designed.cost_usd
    history: list[list[Check]] = []
    for attempt in range(1, attempts + 1):
        built = await build(
            gateway, runner, designed.blueprint,
            seed=seed, tier=tier, feedback=feedback, budget_usd=budget_usd,
        )  # fmt: skip
        cost += built.cost_usd
        history.append(list(built.checks))
        result = PipelineResult(designed, built, attempt, history, cost)
        verdict = "passed the gate" if result.approved else "failed:\n" + failures_text(built)
        progress(f"Attempt {attempt}: {verdict}")
        if result.approved:
            break
        feedback = failures_text(built)
    assert result is not None
    if result.approved:
        progress("Writing the scripted week ...")
        try:
            week = await design_week(gateway, designed.blueprint, tier=tier, budget_usd=budget_usd)
        except Exception as exc:  # the project stays approved; it just has no week yet
            progress(
                f"No week script ({type(exc).__name__}); the project opens as a plain workspace."
            )
        else:
            result.week = week.script
            result.cost_usd += week.cost_usd
    return result


def report_text(result: PipelineResult) -> str:
    gate = "APPROVED (automatic)" if result.approved else "NOT APPROVED"
    head = f"# Gate: {gate} after {result.attempts} attempt(s), cost ${result.cost_usd:.2f}\n\n"
    return head + blueprint_text(result.designed) + "\n\n" + to_text(result.built, None)


def write_output(folder: Path, result: PipelineResult) -> None:
    """Everything a reviewer needs, in one folder: blueprint with its key, checks, files."""
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    (folder / "blueprint.json").write_text(result.designed.blueprint.model_dump_json(indent=2))
    (folder / "report.md").write_text(report_text(result))
    attempts: list[Any] = [
        [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in checks]
        for checks in result.history
    ]
    (folder / "attempts.json").write_text(json.dumps(attempts, indent=2))
    (folder / "metrics.json").write_text(json.dumps(result.built.metrics, indent=2))
    if result.week is not None:
        (folder / "week.json").write_text(result.week.model_dump_json(indent=2))
    for name, files in (
        ("starter", result.built.starter),
        ("reference", result.built.reference),
        ("key", result.built.key),
    ):
        for path, text in files.items():
            target = folder / name / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)


def store_result(findings: Findings, result: PipelineResult, root: Path) -> str:
    """Saves to the database: the draft, its files, and (if the gate passed) the approval."""
    blueprint_id = store_blueprint(findings, result.designed)
    save_artifacts(blueprint_id, result.built, root)
    if result.week is not None:  # after save_artifacts, which clears the folder first
        write_internship(root, blueprint_id, result.week)
    if result.approved:
        with session_scope() as session:
            row = session.get(Blueprint, blueprint_id)
            assert row is not None
            row.validated, row.status = True, "approved"
    return str(blueprint_id)


def export_report(slug: str) -> dict[str, Any]:
    """The newest stored report for a role as a file's worth of JSON."""
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
        return {"slug": slug, "role_name": row[1], "report": row[0].report}


def findings_from_file(path: Path) -> tuple[str, Findings]:
    """(slug, findings) from a file written by `export_report`."""
    raw = json.loads(path.read_text())
    report = RoleRealityReport.model_validate(raw["report"])
    return str(raw["slug"]), findings_from_report(report, str(raw["role_name"]))
