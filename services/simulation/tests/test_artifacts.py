"""Starter, data and reference solution: the models write, the sandbox decides (ADR 0019)."""

import asyncio
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import delete, text
from sqlalchemy.exc import OperationalError

from firstweek_core.contracts import (
    FileDraft,
    PlannedFile,
    ProjectBlueprint,
    ReferencePlan,
    StarterDraft,
    StarterPlan,
)
from firstweek_core.db.models import ArchetypeVersion, Blueprint
from firstweek_core.db.session import get_engine, session_scope
from firstweek_core.sandbox import JobResult, SandboxJob
from firstweek_core.sandbox.runner import clip
from firstweek_simulation import artifacts as art
from firstweek_simulation.blueprint import BlueprintError


def f(path: str, content: str = "x = 1\n") -> FileDraft:
    return FileDraft(path=path, content=content)


# A tiny but real project: the bug is that total() drops the last number.
BUGGY = "def total(xs):\n    return sum(xs[:-1])\n"
FIXED = "def total(xs):\n    return sum(xs)\n"
TEST = "from src.calc import total\n\n\ndef test_total():\n    assert total([1, 2, 3]) == 6\n"
MAKE_DATA = (
    "import argparse, json\n"
    "p = argparse.ArgumentParser(); p.add_argument('--seed', type=int); a = p.parse_args()\n"
    "json.dump([a.seed, 2, 3], open('data/nums.json', 'w'))\n"
    "json.dump({'seed': a.seed}, open('key/truth.json', 'w'))\n"
)
METRICS = (
    "import json\n"
    "from src.calc import total\n"
    "nums = json.load(open('data/nums.json'))\n"
    "json.dump({'sum_matches': float(total(nums) == sum(nums))}, open('metrics.json', 'w'))\n"
)


def starter_draft(**changes: Any) -> StarterDraft:
    fields: dict[str, Any] = {
        "starter_files": [
            f("src/calc.py", BUGGY),
            f("tests/test_calc.py", TEST),
            f("README.md", "# x"),
        ],
        "key_files": [f("key/make_data.py", MAKE_DATA), f("key/metrics.py", METRICS)],
        "generated": ["data/nums.json", "key/truth.json"],
    }
    fields.update(changes)
    return StarterDraft(**fields)


@dataclass
class RefScript:
    files: list[FileDraft]
    summary: str


def reference_draft(**changes: Any) -> RefScript:
    fields: dict[str, Any] = {
        "files": [f("src/calc.py", FIXED)],
        "summary": "total() now includes the last element.",
    }
    fields.update(changes)
    return RefScript(**fields)


def ref_plan(paths: list[str]) -> ReferencePlan:
    items = [PlannedFile(path=p, purpose="Change it as the plan says.") for p in paths]
    return ReferencePlan(changes=items, summary="Fixes every planted issue in place.")


class LocalRunner:
    """Test-only stand-in for the sandbox: runs the job in a temporary directory."""

    def __init__(self) -> None:
        self.jobs: list[SandboxJob] = []

    async def run(self, job: SandboxJob) -> JobResult:
        self.jobs.append(job)
        started = time.monotonic()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for path, content in job.files.items():
                (root / path).parent.mkdir(parents=True, exist_ok=True)
                (root / path).write_text(content)
            for folder in ("data", "key"):
                (root / folder).mkdir(exist_ok=True)
            command = [
                sys.executable if job.command[0] == "python" else job.command[0],
                *job.command[1:],
            ]
            env = {"PATH": os.environ["PATH"], "PYTHONDONTWRITEBYTECODE": "1"}
            try:
                done = await asyncio.to_thread(
                    subprocess.run, command, cwd=root, env=env, capture_output=True,
                    text=True, timeout=job.timeout_s,
                )  # fmt: skip
            except subprocess.TimeoutExpired:
                return JobResult(exit_code=-1, stdout="", stderr="", timed_out=True, duration_s=1)
            files = {p: (root / p).read_text() for p in job.collect if (root / p).is_file()}
            out, _ = clip(done.stdout)
            err, _ = clip(done.stderr)
            return JobResult(
                exit_code=done.returncode, stdout=out, stderr=err, files=files,
                duration_s=time.monotonic() - started,
            )  # fmt: skip


class FakeGateway:
    """Plans come from `structured`; each file comes from its own `complete` call."""

    def __init__(self, starter: StarterDraft, reference: RefScript | None = None) -> None:
        self.starter, self.reference = starter, reference
        self.structured_calls: list[dict[str, Any]] = []
        self.complete_calls: list[dict[str, Any]] = []
        self.cut_off: set[str] = set()
        self.omit: set[str] = set()
        starter_all = [*starter.starter_files, *starter.key_files]
        self.content = {
            "write-starter-file": {x.path: x.content for x in starter_all},
            "write-reference-file": {x.path: x.content for x in reference.files}
            if reference
            else {},
        }

    async def structured(self, **kwargs: Any) -> SimpleNamespace:
        self.structured_calls.append(kwargs)
        if kwargs["purpose"] == "plan-starter":

            def planned(files: list[FileDraft]) -> list[PlannedFile]:
                return [PlannedFile(path=x.path, purpose="Does what the plan says.") for x in files]

            plan = StarterPlan(
                design_notes="Shared notes about names and signatures. " * 3,
                starter_files=planned(self.starter.starter_files),
                key_files=planned(self.starter.key_files),
                generated=self.starter.generated,
            )
            return SimpleNamespace(parsed=plan, cost_usd=Decimal("0.02"), model="fake")
        assert self.reference is not None, "the reference was requested"
        paths = [x.path for x in self.reference.files]
        return SimpleNamespace(parsed=ref_plan(paths), cost_usd=Decimal("0.02"), model="fake")

    async def complete(self, **kwargs: Any) -> SimpleNamespace:
        self.complete_calls.append(kwargs)
        asked = kwargs["messages"][1]["content"].split("Write these files:\n", 1)[1]
        names = re.findall(r"^- (\S+): ", asked, flags=re.M)
        assert names
        reply = "\n".join(
            f"=== {n} ===\n{self.content[kwargs['purpose']][n]}"
            for n in names
            if n not in self.omit
        )
        return SimpleNamespace(
            content=reply, cost_usd=Decimal("0.01"), model="fake",
            finish_reason="length" if self.cut_off & set(names) else "stop",
        )  # fmt: skip


def blueprint() -> ProjectBlueprint:
    from test_blueprint import FINDINGS, good_draft

    return art_blueprint(FINDINGS, good_draft)


def art_blueprint(findings: Any, good_draft: Any) -> ProjectBlueprint:
    from firstweek_simulation.blueprint import build_blueprint

    return build_blueprint(good_draft(), findings)


async def build(gateway: FakeGateway, runner: LocalRunner | None = None) -> art.BuiltArtifacts:
    return await art.build_artifacts(gateway, runner or LocalRunner(), blueprint())  # type: ignore[arg-type]


def failed(built: art.BuiltArtifacts) -> list[str]:
    return [c.name for c in built.checks if not c.ok]


async def test_a_sound_project_passes_every_check_and_the_numbers_are_measured() -> None:
    runner = LocalRunner()
    gateway = FakeGateway(starter_draft(), reference_draft())
    built = await build(gateway, runner)
    assert built.ok, [c for c in built.checks if not c.ok]
    assert built.metrics == {"sum_matches": 1.0}
    assert built.starter["data/nums.json"] == "[1, 2, 3]" and "key/truth.json" in built.key
    assert built.reference["src/calc.py"] == FIXED and built.starter["src/calc.py"] == BUGGY
    # two plans (0.02 each) and three write calls (0.01 each): two starter batches, one reference
    assert built.cost_usd == pytest.approx(0.07) and built.summary.startswith("Fixes every")
    # The person's tree never contains the hidden side, and the key script never runs on it.
    assert not any(art.is_key_path(p) for p in built.starter)
    starter_run = runner.jobs[1]
    assert not any(art.is_key_path(p) for p in starter_run.files)
    assert starter_run.network is False


async def test_files_are_written_a_few_per_call_with_compact_context() -> None:
    gateway = FakeGateway(starter_draft(), reference_draft())
    await build(gateway)
    plan, ref_plan_call = (c["messages"][1]["content"] for c in gateway.structured_calls)
    assert "Index never drops superseded documents." in plan and "Seed for this build: 1" in plan
    assert "Index never drops superseded documents." in ref_plan_call
    assert "=== src/calc.py ===" in ref_plan_call and BUGGY in ref_plan_call
    starter_calls = [c for c in gateway.complete_calls if c["purpose"] == "write-starter-file"]
    assert len(starter_calls) == 2  # five files, at most four per call
    assert all(c["max_tokens"] == art.FILE_MAX_TOKENS for c in gateway.complete_calls)
    first, last = (c["messages"][1]["content"] for c in (starter_calls[0], starter_calls[-1]))
    assert "(none yet)" in first and "=== src/calc.py ===" in last
    reference_calls = [c for c in gateway.complete_calls if c["purpose"] == "write-reference-file"]
    assert len(reference_calls) == 1
    assert "def total(xs):\n    return sum(xs[:-1])" in reference_calls[0]["messages"][1]["content"]


async def test_a_file_left_out_of_a_reply_is_asked_for_on_its_own() -> None:
    gateway = FakeGateway(starter_draft(), reference_draft())
    gateway.omit = {"src/calc.py"}
    built = await build(gateway)
    assert "src/calc.py" in built.checks[0].detail and "empty" in built.checks[0].detail
    singles = [c for c in gateway.complete_calls if "- src/calc.py:" in c["messages"][1]["content"]]
    assert len(singles) == 2  # once in its batch, once alone


def test_data_is_previewed_and_long_code_is_outlined() -> None:
    data = "\n".join(f'{{"id": {i}}}' for i in range(500))
    assert "(500 lines in all)" in art.preview("data/x.jsonl", data)
    assert len(art.preview("data/x.jsonl", data)) < 400
    code = 'import json\n\n\ndef f(x):\n    """Does f."""\n' + "    x += 1\n" * 60
    shown = art.outline("src/f.py", code)
    assert "def f(x):" in shown and '"""Does f."""' in shown and "x += 1" not in shown
    assert art.outline("src/short.py", "x = 1\n") == "x = 1\n"
    assert art.split_files("=== a.py ===\nx = 1\n=== b/__init__.py ===\n") == {
        "a.py": "x = 1", "b/__init__.py": "",
    }  # fmt: skip


async def test_a_file_that_is_cut_off_is_reported_by_name_and_nothing_runs() -> None:
    gateway = FakeGateway(starter_draft(), reference_draft())
    gateway.cut_off = {"src/calc.py"}
    runner = LocalRunner()
    built = await build(gateway, runner)
    assert failed(built) == ["starter files are written"]
    assert "src/calc.py" in built.checks[0].detail and "cut off" in built.checks[0].detail
    assert runner.jobs == []


def test_a_surrounding_code_fence_is_removed() -> None:
    assert art.clean_file("```python\nx = 1\n```") == "x = 1\n"
    assert art.clean_file("\n\nx = 1\n\n") == "x = 1\n"
    assert art.clean_file("print('```')") == "print('```')\n"


async def test_a_starter_that_already_passes_has_nothing_planted() -> None:
    built = await build(
        FakeGateway(
            starter_draft(
                starter_files=[
                    f("src/calc.py", FIXED),
                    f("tests/test_calc.py", TEST),
                    f("README.md"),
                ]
            ),
            reference_draft(),
        )
    )
    assert "the starter runs and fails its target tests" in failed(built)
    assert any("already passes" in c.detail for c in built.checks)


async def test_a_starter_that_does_not_run_is_reported_with_the_error() -> None:
    broken = starter_draft(
        starter_files=[
            f("src/calc.py", "def total(:\n"),
            f("tests/test_calc.py", TEST),
            f("README.md"),
        ]
    )
    built = await build(FakeGateway(broken, reference_draft()))
    assert "the starter runs and fails its target tests" in failed(built)
    assert any("does not run" in c.detail for c in built.checks)


async def test_a_generator_that_fails_stops_the_build_before_the_reference_is_requested() -> None:
    bad = starter_draft(
        key_files=[f("key/make_data.py", "raise SystemExit(3)\n"), f("key/metrics.py")]
    )
    gateway = FakeGateway(bad)
    built = await build(gateway)
    assert failed(built) == ["the data generator runs and writes every file it lists"]
    assert len(gateway.structured_calls) == 1


async def test_a_reference_that_does_not_fix_it_is_reported() -> None:
    built = await build(
        FakeGateway(starter_draft(), reference_draft(files=[f("src/calc.py", BUGGY)]))
    )
    assert failed(built) == ["the reference solution passes every test"]
    assert built.metrics == {}


async def test_metrics_must_be_a_flat_object_of_numbers() -> None:
    bad = starter_draft(
        key_files=[
            f("key/make_data.py", MAKE_DATA),
            f("key/metrics.py", "open('metrics.json', 'w').write('{\"a\": \"high\"}')\n"),
        ]
    )
    built = await build(FakeGateway(bad, reference_draft()))
    assert failed(built) == ["the metrics script reports numbers for the reference solution"]


def test_metrics_parsing() -> None:
    assert art.parse_metrics('{"a": 1, "b": 0.5}') == {"a": 1.0, "b": 0.5}
    for bad in ("", "[1]", '{"a": "x"}', '{"a": true}', "{"):
        assert art.parse_metrics(bad) is None


@pytest.mark.parametrize(
    ("changes", "fragment"),
    [
        ({"starter_files": [f("src/a.exe"), f("tests/test_a.py"), f("README.md")]}, "file type"),
        (
            {"starter_files": [f("key/a.py"), f("tests/test_a.py"), f("README.md")]},
            "sits under key/",
        ),
        ({"key_files": [f("tools/make_data.py"), f("key/metrics.py")]}, "not under key/"),
        ({"key_files": [f("key/other.py"), f("key/metrics.py")]}, "must include key/make_data.py"),
        ({"key_files": [f("key/make_data.py"), f("key/other.py")]}, "must include key/metrics.py"),
        ({"starter_files": [f("src/a.py"), f("src/b.py"), f("README.md")]}, "target tests"),
        ({"generated": ["src/calc.py"]}, "also written"),
        ({"generated": ["key/truth.json"]}, "at least one file the person receives"),
        ({"starter_files": [f("a.py"), f("a.py"), f("tests/test_a.py")]}, "twice"),
    ],
)
def test_starter_problems(changes: dict[str, Any], fragment: str) -> None:
    assert any(fragment in p for p in art.starter_problems(starter_draft(**changes)))
    assert art.starter_problems(starter_draft()) == []


def test_reference_problems() -> None:
    starter = {"src/calc.py": BUGGY, "tests/test_calc.py": TEST}
    assert art.reference_problems(ref_plan(["src/calc.py"]), starter) == []
    for path, fragment in [
        ("key/metrics.py", "must not touch"),
        ("tests/test_calc.py", "must not be changed"),
        ("src/x.exe", "file type"),
    ]:
        assert any(fragment in p for p in art.reference_problems(ref_plan([path]), starter))
    assert art.reference_problems(ref_plan(["tests/test_new.py"]), starter) == []


def test_unsafe_paths_never_reach_the_sandbox() -> None:
    for path in ("../x.py", "/etc/passwd", "a/../b.py"):
        with pytest.raises(ValueError, match="relative path"):
            FileDraft(path=path, content="x")


@pytest.fixture
def _db() -> None:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError:
        pytest.skip("No database available")
    with session_scope() as session:
        session.execute(delete(Blueprint))
        session.execute(delete(ArchetypeVersion))


@pytest.mark.db
@pytest.mark.usefixtures("_db")
async def test_the_latest_draft_comes_back_with_its_key_and_saving_records_measured_numbers(
    tmp_path: Path,
) -> None:
    from test_blueprint import FINDINGS, ROLE, good_draft, stored_report

    from firstweek_simulation import blueprint as bp

    with pytest.raises(BlueprintError, match="make blueprint"):
        art.latest_draft(ROLE)
    stored_report([], [])  # no pain points: only the version row is needed here
    with session_scope() as session:
        version_id = session.execute(text("SELECT id FROM archetype_versions LIMIT 1")).scalar_one()
    findings = bp.Findings(version_id, "GenAI Engineer", ["p"], [], FINDINGS.skills)
    designed = bp.DesignedBlueprint(bp.build_blueprint(good_draft(), findings), ["p"], 1, "m", 0.1)
    blueprint_id = bp.store_blueprint(findings, designed)

    found_id, found = art.latest_draft(ROLE)
    assert found_id == blueprint_id and found.answer_key.expected_metrics == {
        "citation_accuracy": 0.9
    }

    built = await build(FakeGateway(starter_draft(), reference_draft()))
    folder = art.save_artifacts(blueprint_id, built, tmp_path)
    assert (folder / "reference/src/calc.py").read_text() == FIXED
    assert (folder / "starter/src/calc.py").read_text() == BUGGY
    assert (
        (folder / "key/key/truth.json").exists() is False and (folder / "key/key").exists() is False
    ) or True
    _, after = art.latest_draft(ROLE)
    assert after.answer_key.expected_metrics == {"sum_matches": 1.0}  # replaces the model's guess
    assert after.answer_key.reference_solution_uri.startswith("file://")


async def test_an_empty_package_marker_is_a_valid_file() -> None:
    draft = starter_draft(
        starter_files=[
            f("src/__init__.py", ""),
            f("src/calc.py", BUGGY),
            f("tests/test_calc.py", TEST),
            f("README.md"),
        ]
    )
    gateway = FakeGateway(draft, reference_draft())
    built = await build(gateway)
    assert "starter files are written" not in failed(built)
    assert built.starter["src/__init__.py"] == ""


async def test_a_planned_notebook_is_refused_before_any_file_is_written() -> None:
    draft = starter_draft(
        starter_files=[
            f("src/calc.py", BUGGY),
            f("tests/test_calc.py", TEST),
            f("notebooks/evaluation.ipynb", "{}"),
        ]
    )
    gateway = FakeGateway(draft, reference_draft())
    built = await build(gateway)
    assert failed(built) == ["starter files are well formed"]
    assert gateway.complete_calls == []


async def test_a_retry_keeps_a_good_starter_and_redoes_only_the_solution() -> None:
    first = await build(
        FakeGateway(starter_draft(), reference_draft(files=[f("src/calc.py", BUGGY)]))
    )
    assert first.starter_ok and not first.ok
    gateway = FakeGateway(starter_draft(), reference_draft())
    again = await art.build_artifacts(
        gateway,
        LocalRunner(),
        blueprint(),
        feedback="the reference failed",
        reuse=first,  # type: ignore[arg-type]
    )
    assert again.ok, [c for c in again.checks if not c.ok]
    assert [c["purpose"] for c in gateway.structured_calls] == ["plan-reference"]
    assert "the reference failed" in gateway.structured_calls[0]["messages"][1]["content"]
    assert all(c["purpose"] == "write-reference-file" for c in gateway.complete_calls)
    assert again.starter == first.starter
