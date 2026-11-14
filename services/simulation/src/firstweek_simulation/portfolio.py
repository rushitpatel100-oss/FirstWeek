"""Portfolio output for a finished week: a skill matrix, CV bullets and a repo export (M6).

Pure code, no model call. The one rule: a number appears only if it was measured here, from the
final test run, the files the learner changed, or the supervisor's scores. Nothing is invented,
and the bullets say who scored what."""

import io
import json
import re
import zipfile
from dataclasses import dataclass
from typing import Any

from firstweek_core.contracts import SupervisorVerdict
from firstweek_core.sandbox import JobResult
from firstweek_simulation.workspace import Project, with_edits

PASSED = re.compile(r"(\d+) passed")
FAILED = re.compile(r"(\d+) failed")
TEST_FUNC = re.compile(r"^\s*(?:async\s+)?def\s+test_\w+", re.MULTILINE)
SKIP_DIRS = {"key"}  # never leaves the server


@dataclass(frozen=True)
class Measured:
    tests_passed: int
    tests_failed: int
    run_ok: bool
    changed_files: int
    new_tests: int


@dataclass(frozen=True)
class MatrixRow:
    skill_id: str
    score: int
    weight: float
    evidence: str


def measure(project: Project, edits: dict[str, str], tests: JobResult | None) -> Measured:
    passed = failed = 0
    run_ok = False
    if tests is not None:
        text = tests.stdout + tests.stderr
        p, f = PASSED.search(text), FAILED.search(text)
        passed, failed = int(p.group(1)) if p else 0, int(f.group(1)) if f else 0
        run_ok = tests.exit_code == 0 and not tests.timed_out
    merged = with_edits(project, edits)
    changed = [p for p, t in merged.items() if project.files.get(p) != t]
    new_tests = sum(
        len(TEST_FUNC.findall(merged[p]))
        for p in changed
        if p.startswith("tests/") and p.endswith(".py")
    ) - sum(
        len(TEST_FUNC.findall(project.files[p]))
        for p in changed
        if p in project.files and p.startswith("tests/") and p.endswith(".py")
    )
    return Measured(passed, failed, run_ok, len(changed), max(new_tests, 0))


def skill_matrix(project: Project, verdict: SupervisorVerdict) -> list[MatrixRow]:
    """The supervisor's scores laid against the project's rubric weights, strongest first."""
    weights = {c["skill_id"]: float(c["weight"]) for c in project.blueprint["rubric"]}
    rows = [
        MatrixRow(s.skill_id, s.score, weights.get(s.skill_id, 0.0), s.evidence)
        for s in verdict.skills
    ]
    return sorted(rows, key=lambda r: (-r.score, -r.weight, r.skill_id))


def weighted_score(rows: list[MatrixRow]) -> float | None:
    """The rubric-weighted mean out of 5, or None when no scored skill is in the rubric."""
    total = sum(r.weight for r in rows)
    if total <= 0:
        return None
    return round(sum(r.score * r.weight for r in rows) / total, 2)


def _label(skill_id: str) -> str:
    return skill_id.replace("-", " ").replace("_", " ")


def cv_bullets(
    role: str, project: Project, rows: list[MatrixRow], m: Measured, *, reviewer: str
) -> list[str]:
    """Bullets built only from measured facts. Skills the supervisor scored 4 or more are named;
    lower ones are left out rather than dressed up."""
    scenario = str(project.blueprint.get("scenario", "")).strip().rstrip(".")
    lead = f"Completed a five-day simulated {role} project"
    if scenario:
        lead += f": {scenario[:140]}"
    bullets = [lead + " (practice simulation, not employment)."]
    if m.run_ok and m.tests_passed:
        bullets.append(
            f"Finished with all {m.tests_passed} automated tests passing in a sandbox"
            + (f", including {m.new_tests} I wrote." if m.new_tests else ".")
        )
    elif m.tests_passed or m.tests_failed:
        bullets.append(
            f"Ran the project's tests in a sandbox ({m.tests_passed} passing, "
            f"{m.tests_failed} failing at the end of the week)."
        )
    strong = [r for r in rows if r.score >= 4]
    if strong:
        names = ", ".join(_label(r.skill_id) for r in strong[:3])
        bullets.append(f"Rated 4 or 5 out of 5 on {names} by an AI supervisor ({reviewer}).")
    return bullets


def _readme(
    role: str, project: Project, rows: list[MatrixRow], m: Measured, score: float | None
) -> str:
    lines = [
        f"# {role}: practice week",
        "",
        "Work from a simulated five-day project on FirstWeek. It is practice, not a job.",
        "",
        f"**Scenario.** {project.blueprint.get('scenario', '')}",
        "",
        "## Skill matrix",
        "",
        "| Skill | Score (1-5) | Rubric weight |",
        "| --- | --- | --- |",
        *[f"| {_label(r.skill_id)} | {r.score} | {r.weight:g} |" for r in rows],
        "",
    ]
    if score is not None:
        lines += [f"Weighted score: {score} out of 5, scored by an AI supervisor.", ""]
    lines += [
        "## Measured",
        "",
        f"- Tests passing at the end: {m.tests_passed}; failing: {m.tests_failed}",
        f"- Files changed from the starter: {m.changed_files}",
        f"- Tests added: {m.new_tests}",
        "",
    ]
    return "\n".join(lines)


def build_export(
    role: str,
    project: Project,
    edits: dict[str, str],
    tests: JobResult | None,
    verdict: SupervisorVerdict,
    *,
    reviewer: str,
) -> tuple[dict[str, Any], bytes]:
    """The portfolio summary (JSON-ready) and a zip of the learner's repo with it."""
    m = measure(project, edits, tests)
    rows = skill_matrix(project, verdict)
    score = weighted_score(rows)
    bullets = cv_bullets(role, project, rows, m, reviewer=reviewer)
    summary: dict[str, Any] = {
        "role": role,
        "weighted_score": score,
        "skill_matrix": [r.__dict__ for r in rows],
        "measured": m.__dict__,
        "cv_bullets": bullets,
        "reviewer": reviewer,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path, text in sorted(with_edits(project, edits).items()):
            if path.split("/")[0] not in SKIP_DIRS:
                z.writestr(f"repo/{path}", text)
        z.writestr("repo/PRACTICE.md", _readme(role, project, rows, m, score))
        z.writestr("CV_BULLETS.md", "\n".join(f"- {b}" for b in bullets) + "\n")
        z.writestr("skill_matrix.json", json.dumps(summary, indent=2))
    return summary, buf.getvalue()
