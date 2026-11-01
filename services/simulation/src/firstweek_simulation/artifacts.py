"""Starter repository, dataset and reference solution for a blueprint (ADR 0019).

Models write the files; code runs them in the sandbox and records what happened. Every
number in the answer key's metrics comes from running the reference solution, never from a
model's guess. This module builds and measures; the validation gate (next step) decides what
is acceptable and regenerates."""

import json
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from sqlalchemy import select

from firstweek_core.contracts import (
    ProjectBlueprint,
    ReferenceDraft,
    StarterDraft,
)
from firstweek_core.db.models import ArchetypeVersion, Blueprint, RoleArchetype
from firstweek_core.db.session import session_scope
from firstweek_core.llm import LLMGateway
from firstweek_core.llm import Tier as ModelTier
from firstweek_core.sandbox import SandboxJob, SandboxRunner
from firstweek_simulation.blueprint import BlueprintError, load_prompt

STARTER_VERSION = "build-starter.v2"
REFERENCE_VERSION = "build-reference.v1"
ARTIFACT_TIER: ModelTier = "mid"
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


def reference_problems(draft: ReferenceDraft, starter: dict[str, str]) -> list[str]:
    problems: list[str] = []
    paths = [f.path for f in draft.files]
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


async def build_artifacts(
    gateway: LLMGateway,
    runner: SandboxRunner,
    blueprint: ProjectBlueprint,
    *,
    seed: int = SHARED_SEED,
    budget_usd: float = 1.0,
) -> BuiltArtifacts:
    """Writes, generates and runs everything. Returns the result with every check, pass or fail."""
    tickets, rubric, issues = listing(blueprint)
    system, user = load_prompt(STARTER_VERSION)
    first = await gateway.structured(
        purpose="build-starter",
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
                ),
            },
        ],
        response_model=StarterDraft,
        tier=ARTIFACT_TIER,
        max_tokens=32000,  # the ceiling: a cut-off first try would be paid for twice
        temperature=0.4,
        budget_scope="build-artifacts",
        budget_usd=budget_usd,
        prompt_version=STARTER_VERSION,
    )
    assert first.parsed is not None
    draft = first.parsed
    built = BuiltArtifacts(
        starter={}, reference={}, key={}, metrics={}, summary="",
        cost_usd=float(first.cost_usd), model=first.model,
    )  # fmt: skip
    if problems := starter_problems(draft):
        built.checks.append(Check("starter files are well formed", False, " ".join(problems)))
        return built
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
    if not generated_ok:
        built.starter, built.key = starter, key
        return built
    for path, text in made.files.items():
        (key if is_key_path(path) else starter)[path] = text
    built.starter, built.key = dict(starter), dict(key)

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

    system, user = load_prompt(REFERENCE_VERSION)
    shown = "\n\n".join(f"=== {p} ===\n{c}" for p, c in sorted(starter.items()))
    second = await gateway.structured(
        purpose="build-reference",
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": user.format(
                    scenario=blueprint.scenario, tickets=tickets, issues=issues, starter=shown
                ),
            },
        ],
        response_model=ReferenceDraft,
        tier=ARTIFACT_TIER,
        max_tokens=24000,
        temperature=0.2,
        budget_scope="build-artifacts",
        budget_usd=budget_usd,
        prompt_version=REFERENCE_VERSION,
    )
    assert second.parsed is not None
    built.cost_usd += float(second.cost_usd)
    ref = second.parsed
    built.summary = ref.summary
    if problems := reference_problems(ref, starter):
        built.checks.append(Check("reference files are well formed", False, " ".join(problems)))
        return built
    built.checks.append(Check("reference files are well formed", True))
    reference = tree(starter, {f.path: f.content for f in ref.files})
    built.reference = reference

    after = await runner.run(SandboxJob(files=dict(reference), command=TEST_COMMAND, timeout_s=120))
    passed = after.ok
    built.checks.append(
        Check(
            "the reference solution passes every test",
            passed,
            "" if passed else f"exit {after.exit_code}: {tail(after.stdout + after.stderr)}",
        )
    )
    if not passed:
        return built

    measured = await runner.run(
        SandboxJob(
            files=tree(reference, key),
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
    return built


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
