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

from firstweek_core.contracts import Internship, ProjectBlueprint, RoleRealityReport
from firstweek_core.db.models import ArchetypeVersion, Blueprint, RoleArchetype, RoleReport
from firstweek_core.db.session import session_scope
from firstweek_core.llm import FreeQuotaExhaustedError, LLMGateway
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
# The most model calls one run can make: design (up to 3 tries), a first build (plan, four
# batches, a split or a missing file, reference plan and write), two retries that rebuild
# everything, and the week (up to 3 tries). A typical run makes about 10.
WORST_CASE_CALLS = 3 + 3 * 10 + 3
CHECKPOINT = "checkpoint.json"


class PipelinePausedError(Exception):
    """Every free model ran out mid-run. Progress is saved; the same command continues it."""


def save_checkpoint(
    path: Path, designed: DesignedBlueprint, done: int, feedback: str, built: BuiltArtifacts | None
) -> None:
    """What a later run needs to continue: the blueprint, attempts used, and a starter that
    passed its checks (so it is never paid for twice)."""
    starter = None
    if built is not None and built.starter_ok:
        starter = {
            "starter": built.starter,
            "key": built.key,
            "design_notes": built.design_notes,
            "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in built.checks],
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "blueprint": designed.blueprint.model_dump(mode="json"),
                "grounded_in": designed.grounded_in,
                "model": designed.model,
                "cost_usd": designed.cost_usd,
                "attempts_done": done,
                "feedback": feedback,
                "starter": starter,
            }
        )
    )


def clear_checkpoint(path: Path) -> None:
    path.unlink(missing_ok=True)


def load_checkpoint(
    path: Path,
) -> tuple[DesignedBlueprint, int, str, BuiltArtifacts | None] | None:
    if not path.is_file():
        return None
    raw = json.loads(path.read_text())
    designed = DesignedBlueprint(
        ProjectBlueprint.model_validate(raw["blueprint"]),
        list(raw["grounded_in"]), 1, str(raw["model"]), float(raw["cost_usd"]),
    )  # fmt: skip
    built = None
    if raw.get("starter"):
        saved = raw["starter"]
        built = BuiltArtifacts(
            starter=saved["starter"], reference={}, key=saved["key"], metrics={}, summary="",
            checks=[Check(c["name"], c["ok"], c["detail"]) for c in saved["checks"]],
            design_notes=str(saved.get("design_notes", "")),
        )  # fmt: skip
    return designed, int(raw["attempts_done"]), str(raw["feedback"]), built


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
    checkpoint: Path | None = None,
) -> PipelineResult:
    saved = load_checkpoint(checkpoint) if checkpoint is not None else None
    if saved is not None:
        designed, done, feedback, previous = saved
        progress(
            f"Continuing a saved run: blueprint kept, {done} attempt(s) used"
            + (", starter kept." if previous is not None else ".")
        )
    else:
        progress(f"Designing the blueprint for {findings.role_name} ({tier} tier) ...")
        try:
            designed = await design_blueprint(
                gateway, slug, findings, tier=tier, budget_usd=budget_usd
            )
        except FreeQuotaExhaustedError as exc:
            raise PipelinePausedError(
                "The free models ran out before the blueprint was designed. Nothing was saved, "
                "nothing was lost: run the same command after the quota resets."
            ) from exc
        done, feedback, previous = 0, "", None
        if checkpoint is not None:
            save_checkpoint(checkpoint, designed, 0, "", None)
        progress(
            f"Blueprint ready: {len(designed.blueprint.tickets)} tickets. Building the project ..."
        )
    result: PipelineResult | None = None
    cost = designed.cost_usd
    history: list[list[Check]] = []
    reused_last = False
    for attempt in range(done + 1, attempts + 1):
        # A good starter is kept once, to redo only the solution. If that fails too, the next
        # attempt starts fresh: the starter's own tests may be what cannot be satisfied.
        reuse = (
            previous if previous is not None and previous.starter_ok and not reused_last else None
        )
        reused_last = reuse is not None
        try:
            built = await build(
                gateway, runner, designed.blueprint,
                seed=seed, tier=tier, feedback=feedback, budget_usd=budget_usd, reuse=reuse,
            )  # fmt: skip
        except FreeQuotaExhaustedError as exc:
            if checkpoint is not None:
                save_checkpoint(checkpoint, designed, attempt - 1, feedback, previous)
            raise PipelinePausedError(
                f"The free models ran out during attempt {attempt}. Progress is saved: run the "
                "same command after the quota resets and it continues from here."
            ) from exc
        except Exception as exc:  # an attempt that crashed is a failed attempt, not a lost run
            built = BuiltArtifacts(
                starter={}, reference={}, key={}, metrics={}, summary="",
                checks=[Check("the build ran", False, f"{type(exc).__name__}: {str(exc)[:500]}")],
            )  # fmt: skip
        cost += built.cost_usd
        history.append(list(built.checks))
        result = PipelineResult(designed, built, attempt, history, cost)
        verdict = "passed the gate" if result.approved else "failed:\n" + failures_text(built)
        progress(f"Attempt {attempt}: {verdict}")
        if result.approved:
            break
        feedback = failures_text(built)
        if built.starter_ok:
            previous = built
        if checkpoint is not None:
            save_checkpoint(checkpoint, designed, attempt, feedback, previous)
    if checkpoint is not None:
        clear_checkpoint(checkpoint)  # finished, approved or not: the next run starts fresh
    if result is None:
        raise PipelinePausedError("No attempts were left in the saved run.")
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
