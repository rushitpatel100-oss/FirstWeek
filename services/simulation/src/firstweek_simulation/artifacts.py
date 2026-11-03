"""Starter repository, dataset and reference solution for a blueprint (ADR 0019).

Models write the files; code runs them in the sandbox and records what happened. Every
number in the answer key's metrics comes from running the reference solution, never from a
model's guess. This module builds and measures; the validation gate (next step) decides what
is acceptable and regenerates."""

import json
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from pydantic import ValidationError
from sqlalchemy import select

from firstweek_core.contracts import (
    FileDraft,
    PlannedFile,
    ProjectBlueprint,
    ReferencePlan,
    StarterDraft,
    StarterPlan,
)
from firstweek_core.db.models import ArchetypeVersion, Blueprint, RoleArchetype
from firstweek_core.db.session import session_scope
from firstweek_core.llm import LLMGateway
from firstweek_core.llm import Tier as ModelTier
from firstweek_core.sandbox import SandboxJob, SandboxRunner
from firstweek_simulation.blueprint import BlueprintError, load_prompt

PLAN_STARTER_VERSION = "plan-starter.v3"
WRITE_FILE_VERSION = "write-file.v1"
PLAN_REFERENCE_VERSION = "plan-reference.v1"
WRITE_REFERENCE_VERSION = "write-reference-file.v1"
PLAN_MAX_TOKENS = 12000
FILE_MAX_TOKENS = 8000
ALLOWED_SUFFIXES = {
    ".py", ".md", ".txt", ".json", ".jsonl", ".csv", ".log",
    ".toml", ".cfg", ".ini", ".yaml", ".yml",
}  # fmt: skip
KEY_DIR = "key"
GENERATOR = f"{KEY_DIR}/make_data.py"
METRICS_SCRIPT = f"{KEY_DIR}/metrics.py"
TEST_COMMAND = ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]
SHARED_SEED = 1
PYTEST_FAILED = 1  # pytest's exit code when tests ran and some failed


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class BuiltArtifacts:
    starter: dict[str, str]  # what the person receives, data included
    reference: dict[str, str]  # the starter with the reference solution applied
    key: dict[str, str]  # hidden files, generated truth included
    metrics: dict[str, float]
    summary: str
    checks: list[Check] = field(default_factory=list)
    cost_usd: float = 0.0
    model: str = ""

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)


def is_key_path(path: str) -> bool:
    return PurePosixPath(path).parts[0] == KEY_DIR


def starter_problems(draft: StarterDraft) -> list[str]:
    """What is wrong with the files before anything runs."""
    problems: list[str] = []
    starter = [f.path for f in draft.starter_files]
    key = [f.path for f in draft.key_files]
    every = [*starter, *key, *draft.generated]
    for path in every:
        if PurePosixPath(path).suffix not in ALLOWED_SUFFIXES:
            problems.append(f"{path}: file type not allowed.")
    if len(set(starter)) != len(starter) or len(set(key)) != len(key):
        problems.append("A path appears twice.")
    problems += [
        f"{p} is a starter file but sits under {KEY_DIR}/." for p in starter if is_key_path(p)
    ]
    problems += [
        f"{p} is a key file but is not under {KEY_DIR}/." for p in key if not is_key_path(p)
    ]
    for needed in (GENERATOR, METRICS_SCRIPT):
        if needed not in key:
            problems.append(f"key_files must include {needed}.")
    if not any(p.startswith("tests/") and p.endswith(".py") for p in starter):
        problems.append("The starter needs target tests under tests/.")
    clash = sorted(set(draft.generated) & set(starter + key))
    if clash:
        problems.append(f"Generated files are also written as files: {clash}.")
    if not any(not is_key_path(p) for p in draft.generated):
        problems.append("make_data.py must write at least one file the person receives.")
    return problems


def reference_problems(draft: ReferencePlan, starter: dict[str, str]) -> list[str]:
    problems: list[str] = []
    paths = [f.path for f in draft.changes]
    if len(set(paths)) != len(paths):
        problems.append("A path appears twice.")
    for path in paths:
        if PurePosixPath(path).suffix not in ALLOWED_SUFFIXES:
            problems.append(f"{path}: file type not allowed.")
        if is_key_path(path):
            problems.append(f"{path}: the solution must not touch {KEY_DIR}/.")
        if path.startswith("tests/") and path in starter:
            problems.append(f"{path}: existing tests must not be changed.")
    return problems


def tree(*parts: dict[str, str]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for part in parts:
        merged.update(part)
    return merged


def listing(blueprint: ProjectBlueprint) -> tuple[str, str, str]:
    tickets = "\n".join(
        f"- {t.key} ({t.task_type}, day {t.due_day}): {t.title}\n"
        + "\n".join(f"    * {c}" for c in t.acceptance_criteria)
        for t in blueprint.tickets
    )
    rubric = "\n".join(f"- {c.skill_id}: " + "; ".join(c.checks) for c in blueprint.rubric)
    issues = "\n".join(f"- {i}" for i in blueprint.answer_key.planted_issues)
    return tickets, rubric, issues


def tail(text: str, lines: int = 12) -> str:
    return "\n".join(text.strip().splitlines()[-lines:])


class FileWriteError(Exception):
    """A file could not be written: the reply was cut off or empty."""


def clean_file(text: str) -> str:
    """The file as written, without a surrounding code fence."""
    body = text.strip("\n")
    lines = body.splitlines()
    if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
        body = "\n".join(lines[1:-1])
    return body.rstrip() + "\n"


@dataclass
class Spend:
    cost_usd: float = 0.0
    model: str = ""


async def write_files(
    gateway: LLMGateway,
    spend: Spend,
    *,
    purpose: str,
    version: str,
    tier: ModelTier,
    planned: list[PlannedFile],
    render: Callable[[PlannedFile, dict[str, str]], dict[str, str]],
    budget_usd: float,
) -> dict[str, str]:
    """One model call per file, in order, each seeing the files before it.

    Small replies keep a long project from being cut off, and a bad file costs one call."""
    system, user = load_prompt(version)
    written: dict[str, str] = {}
    for item in planned:
        result = await gateway.complete(
            purpose=purpose,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user.format(**render(item, written))},
            ],
            tier=tier,
            max_tokens=FILE_MAX_TOKENS,
            temperature=0.3,
            budget_scope="build-artifacts",
            budget_usd=budget_usd,
            prompt_version=version,
        )
        spend.cost_usd += float(result.cost_usd)
        spend.model = result.model
        if result.finish_reason == "length":
            raise FileWriteError(f"{item.path}: the reply was cut off at {FILE_MAX_TOKENS} tokens")
        if not result.content.strip():
            if PurePosixPath(item.path).name == "__init__.py":
                written[item.path] = ""  # an empty package marker is a valid file
                continue
            raise FileWriteError(f"{item.path}: the reply was empty")
        written[item.path] = clean_file(result.content)
    return written


def shown(files: dict[str, str]) -> str:
    return "\n\n".join(f"=== {p} ===\n{c}" for p, c in sorted(files.items())) or "(none yet)"


def plan_text(items: list[PlannedFile]) -> str:
    return "\n".join(f"- {i.path}: {i.purpose}" for i in items)


async def build_artifacts(
    gateway: LLMGateway,
    runner: SandboxRunner,
    blueprint: ProjectBlueprint,
    *,
    seed: int = SHARED_SEED,
    tier: ModelTier = "judge",
    feedback: str = "",
    budget_usd: float = 1.0,
) -> BuiltArtifacts:
    """Plans, writes, generates and runs everything. Returns every check, pass or fail."""
    tickets, rubric, issues = listing(blueprint)
    spend = Spend()
    built = BuiltArtifacts(starter={}, reference={}, key={}, metrics={}, summary="")

    def finish() -> BuiltArtifacts:
        built.cost_usd, built.model = spend.cost_usd, spend.model
        return built

    system, user = load_prompt(PLAN_STARTER_VERSION)
    planned = await gateway.structured(
        purpose="plan-starter",
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": user.format(
                    role_name=blueprint.archetype,
                    scenario=blueprint.scenario,
                    company=blueprint.company_context,
                    tickets=tickets,
                    rubric=rubric,
                    issues=issues,
                    seed=seed,
                    feedback=feedback or "(none: this is the first attempt)",
                ),
            },
        ],
        response_model=StarterPlan,
        tier=tier,
        max_tokens=PLAN_MAX_TOKENS,
        temperature=0.4,
        budget_scope="build-artifacts",
        budget_usd=budget_usd,
        prompt_version=PLAN_STARTER_VERSION,
    )
    assert planned.parsed is not None
    plan = planned.parsed
    spend.cost_usd += float(planned.cost_usd)
    spend.model = planned.model
    every = [*plan.starter_files, *plan.key_files]
    if bad := [i.path for i in every if PurePosixPath(i.path).suffix not in ALLOWED_SUFFIXES]:
        built.checks.append(
            Check("starter files are well formed", False, f"{bad}: file type not allowed.")
        )
        return finish()

    def render_starter(item: PlannedFile, written: dict[str, str]) -> dict[str, str]:
        return {
            "scenario": blueprint.scenario,
            "notes": plan.design_notes,
            "plan": plan_text(every),
            "written": shown(written),
            "path": item.path,
            "purpose": item.purpose,
        }

    try:
        files = await write_files(
            gateway, spend, purpose="write-starter-file", version=WRITE_FILE_VERSION, tier=tier,
            planned=every, render=render_starter, budget_usd=budget_usd,
        )  # fmt: skip
        draft = StarterDraft(
            starter_files=[
                FileDraft(path=i.path, content=files[i.path]) for i in plan.starter_files
            ],
            key_files=[FileDraft(path=i.path, content=files[i.path]) for i in plan.key_files],
            generated=plan.generated,
        )
    except (FileWriteError, ValidationError) as exc:
        built.checks.append(Check("starter files are written", False, str(exc)[:600]))
        return finish()
    if problems := starter_problems(draft):
        built.checks.append(Check("starter files are well formed", False, " ".join(problems)))
        return finish()
    built.checks.append(Check("starter files are well formed", True))

    starter = {f.path: f.content for f in draft.starter_files}
    key = {f.path: f.content for f in draft.key_files}

    made = await runner.run(
        SandboxJob(
            files=tree(starter, key),
            command=["python", "-m", "key.make_data", "--seed", str(seed)],
            collect=draft.generated,
            timeout_s=60,
        )
    )
    missing = [p for p in draft.generated if p not in made.files]
    generated_ok = made.ok and not missing
    built.checks.append(
        Check(
            "the data generator runs and writes every file it lists",
            generated_ok,
            ""
            if generated_ok
            else f"exit {made.exit_code}; missing {missing}; {tail(made.stderr)}",
        )
    )
    built.starter, built.key = dict(starter), dict(key)
    if not generated_ok:
        return finish()
    for path, text in made.files.items():
        (built.key if is_key_path(path) else built.starter)[path] = text
    starter = built.starter

    before = await runner.run(SandboxJob(files=dict(starter), command=TEST_COMMAND, timeout_s=120))
    if before.timed_out:
        verdict = "the starter's tests timed out"
    elif before.exit_code == PYTEST_FAILED:
        verdict = ""
    elif before.exit_code == 0:
        verdict = "the starter already passes its tests, so nothing is planted"
    else:
        output = tail(before.stdout + before.stderr)
        verdict = f"the starter does not run (pytest exit {before.exit_code}): {output}"
    built.checks.append(Check("the starter runs and fails its target tests", not verdict, verdict))

    system, user = load_prompt(PLAN_REFERENCE_VERSION)
    ref_planned = await gateway.structured(
        purpose="plan-reference",
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": user.format(
                    scenario=blueprint.scenario,
                    tickets=tickets,
                    issues=issues,
                    starter=shown(starter),
                ),
            },
        ],
        response_model=ReferencePlan,
        tier=tier,
        max_tokens=PLAN_MAX_TOKENS,
        temperature=0.2,
        budget_scope="build-artifacts",
        budget_usd=budget_usd,
        prompt_version=PLAN_REFERENCE_VERSION,
    )
    assert ref_planned.parsed is not None
    ref_plan = ref_planned.parsed
    spend.cost_usd += float(ref_planned.cost_usd)
    built.summary = ref_plan.summary
    if problems := reference_problems(ref_plan, starter):
        built.checks.append(Check("reference plan is well formed", False, " ".join(problems)))
        return finish()

    def render_reference(item: PlannedFile, written: dict[str, str]) -> dict[str, str]:
        return {
            "scenario": blueprint.scenario,
            "plan": plan_text(ref_plan.changes),
            "starter": shown(starter),
            "written": shown(written),
            "path": item.path,
            "purpose": item.purpose,
        }

    try:
        changed = await write_files(
            gateway, spend, purpose="write-reference-file", tier=tier,
            version=WRITE_REFERENCE_VERSION, planned=ref_plan.changes,
            render=render_reference, budget_usd=budget_usd,
        )  # fmt: skip
    except FileWriteError as exc:
        built.checks.append(Check("reference files are written", False, str(exc)))
        return finish()
    built.checks.append(Check("reference files are written", True))
    reference = tree(starter, changed)
    built.reference = reference

    after = await runner.run(SandboxJob(files=dict(reference), command=TEST_COMMAND, timeout_s=120))
    built.checks.append(
        Check(
            "the reference solution passes every test",
            after.ok,
            "" if after.ok else f"exit {after.exit_code}: {tail(after.stdout + after.stderr)}",
        )
    )
    if not after.ok:
        return finish()

    measured = await runner.run(
        SandboxJob(
            files=tree(reference, built.key),
            command=["python", "-m", "key.metrics"],
            collect=["metrics.json"],
            timeout_s=60,
        )
    )
    metrics = parse_metrics(measured.files.get("metrics.json", ""))
    metrics_ok = measured.ok and metrics is not None and bool(metrics)
    built.checks.append(
        Check(
            "the metrics script reports numbers for the reference solution",
            metrics_ok,
            "" if metrics_ok else f"exit {measured.exit_code}: {tail(measured.stderr)}",
        )
    )
    if metrics_ok and metrics is not None:
        built.metrics = metrics
    return finish()


def parse_metrics(text: str) -> dict[str, float] | None:
    """A flat object of numbers, or None if it is anything else."""
    try:
        raw = json.loads(text)
    except ValueError:
        return None
    if not isinstance(raw, dict):
        return None
    out: dict[str, float] = {}
    for name, value in raw.items():
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        out[str(name)] = float(value)
    return out


def latest_draft(slug: str) -> tuple[uuid.UUID, ProjectBlueprint]:
    """The newest stored draft blueprint for a role, with its answer key put back."""
    with session_scope() as session:
        row = session.execute(
            select(Blueprint)
            .join(ArchetypeVersion, ArchetypeVersion.id == Blueprint.archetype_version_id)
            .join(RoleArchetype, RoleArchetype.id == ArchetypeVersion.archetype_id)
            .where(RoleArchetype.slug == slug)
            .order_by(Blueprint.created_at.desc())
            .limit(1)
        ).scalar()
        if row is None:
            raise BlueprintError("No blueprint for this role. Run `make blueprint` first.")
        return row.id, ProjectBlueprint.model_validate(
            {**row.blueprint, "answer_key": row.answer_key}
        )


def save_artifacts(blueprint_id: uuid.UUID, built: BuiltArtifacts, root: Path) -> Path:
    """Writes starter, reference and key under root/<id>/ and points the answer key at it.

    The measured metrics replace anything the design guessed. The blueprint stays unvalidated."""
    folder = root / str(blueprint_id)
    shutil.rmtree(folder, ignore_errors=True)
    for name, files in (
        ("starter", built.starter),
        ("reference", built.reference),
        ("key", built.key),
    ):
        for path, text in files.items():
            target = folder / name / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
    with session_scope() as session:
        row = session.get(Blueprint, blueprint_id)
        assert row is not None
        key = dict(row.answer_key)
        key["reference_solution_uri"] = (folder / "reference").resolve().as_uri()
        if built.metrics:
            key["expected_metrics"] = built.metrics
        row.answer_key = key
    return folder


def to_text(built: BuiltArtifacts, folder: Path | None) -> str:
    lines = ["# Starter, data and reference solution", ""]
    lines += [
        f"- {'PASS' if c.ok else 'FAIL'}: {c.name}" + (f"\n    {c.detail}" if c.detail else "")
        for c in built.checks
    ]
    if built.metrics:
        lines += ["", "## Measured from the reference solution"]
        lines += [f"- {name}: {value:g}" for name, value in sorted(built.metrics.items())]
    if built.summary:
        lines += ["", "## What the reference changes", built.summary]
    lines += ["", f"_Model: {built.model}. Cost: ${built.cost_usd:.2f}._"]
    if folder is not None:
        lines.append(f"Files: {folder}")
    return "\n".join(lines)
