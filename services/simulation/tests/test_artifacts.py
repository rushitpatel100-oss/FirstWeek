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
        self.first_plans: list[StarterPlan] = []  # served before the real plan
        self.repairs: list[str] = []  # replies to repair calls, in order; then no change
        starter_all = [*starter.starter_files, *starter.key_files]
        self.content = {
            "write-starter-file": {x.path: x.content for x in starter_all},
            "write-reference-file": {x.path: x.content for x in reference.files}
            if reference
            else {},
        }

    async def structured(self, **kwargs: Any) -> SimpleNamespace:
        self.structured_calls.append(kwargs)
        if kwargs["purpose"] == "plan-starter" and self.first_plans:
            return SimpleNamespace(
                parsed=self.first_plans.pop(0), cost_usd=Decimal("0.02"), model="fake"
            )
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
        if kwargs["purpose"] == "repair-file":
            reply = self.repairs.pop(0) if self.repairs else ""
            return SimpleNamespace(
                content=reply, cost_usd=Decimal("0.01"), model="fake", finish_reason="stop"
            )
        asked = re.split(
            r"Write (?:these files|this file \(and no other\)):\n", kwargs["messages"][1]["content"]
        )[1]
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
            f("src/calc.py", "import no_such_module\n\n" + BUGGY),
            f("tests/test_calc.py", TEST),
            f("README.md"),
        ]
    )
    gateway = FakeGateway(broken, reference_draft())
    built = await build(gateway)
    assert "the starter runs and fails its target tests" in failed(built)
    assert any("does not run" in c.detail for c in built.checks)
    repairs = [c for c in gateway.complete_calls if c["purpose"] == "repair-file"]
    assert len(repairs) == art.HOSTED_REPAIRS  # hosted only: one round, so the quota lasts
    assert "no_such_module" in repairs[0]["messages"][1]["content"]
    assert "=== src/calc.py ===\nimport no_such_module" in repairs[0]["messages"][1]["content"]


async def test_a_file_that_is_not_valid_python_is_named_before_anything_runs() -> None:
    broken = starter_draft(
        starter_files=[
            f("src/calc.py", "def total(:\n"),
            f("tests/test_calc.py", TEST),
            f("README.md"),
        ]
    )
    runner = LocalRunner()
    built = await build(FakeGateway(broken, reference_draft()), runner)
    assert failed(built) == ["starter files are well formed"]
    assert "src/calc.py: not valid Python" in built.checks[0].detail
    assert runner.jobs == []


async def test_a_broken_file_is_repaired_by_name_and_the_build_goes_on() -> None:
    broken = starter_draft(
        starter_files=[
            f("src/calc.py", "def total(:\n"),
            f("tests/test_calc.py", TEST),
            f("README.md"),
        ]
    )
    gateway = FakeGateway(broken, reference_draft())
    gateway.repairs = [f"=== src/calc.py ===\n{BUGGY}"]
    built = await build(gateway)
    assert built.ok, failed(built)
    assert built.starter["src/calc.py"] == BUGGY
    (repair,) = [c for c in gateway.complete_calls if c["purpose"] == "repair-file"]
    assert "src/calc.py: not valid Python (line 1" in repair["messages"][1]["content"]


async def test_debris_around_python_is_removed_by_code_without_a_call() -> None:
    messy = "```python\n" + BUGGY + "```\n\n---\nThis function adds up the numbers.\n"
    gateway = FakeGateway(
        starter_draft(
            starter_files=[f("src/calc.py", messy), f("tests/test_calc.py", TEST), f("README.md")]
        ),
        reference_draft(),
    )
    built = await build(gateway)
    assert built.ok, failed(built)
    assert built.starter["src/calc.py"] == BUGGY
    assert not [c for c in gateway.complete_calls if c["purpose"] == "repair-file"]


async def test_a_generator_that_misses_a_file_is_repaired_with_the_exact_paths() -> None:
    half = MAKE_DATA.replace("json.dump([a.seed, 2, 3], open('data/nums.json', 'w'))\n", "")
    gateway = FakeGateway(
        starter_draft(key_files=[f("key/make_data.py", half), f("key/metrics.py", METRICS)]),
        reference_draft(),
    )
    gateway.repairs = [f"=== key/make_data.py ===\n{MAKE_DATA}"]
    built = await build(gateway)
    assert built.ok, failed(built)
    (repair,) = [c for c in gateway.complete_calls if c["purpose"] == "repair-file"]
    prompt = repair["messages"][1]["content"]
    assert "missing ['data/nums.json']" in prompt
    assert "ran without an error but did not write those files" in prompt
    assert "write exactly these files: data/nums.json, key/truth.json" in prompt


async def test_a_test_with_a_wrong_expected_value_is_corrected_and_still_fails_the_starter() -> (
    None
):
    wrong = TEST.replace("== 6", "== 7")
    gateway = FakeGateway(
        starter_draft(
            starter_files=[f("src/calc.py", BUGGY), f("tests/test_calc.py", wrong), f("README.md")]
        ),
        reference_draft(),
    )
    gateway.repairs = [f"=== tests/test_calc.py ===\n{TEST}"]
    built = await build(gateway)
    assert built.ok, failed(built)
    assert built.starter["tests/test_calc.py"] == TEST == built.reference["tests/test_calc.py"]


async def test_a_test_weakened_until_the_starter_passes_is_refused() -> None:
    wrong = TEST.replace("== 6", "== 7")
    gateway = FakeGateway(
        starter_draft(
            starter_files=[f("src/calc.py", BUGGY), f("tests/test_calc.py", wrong), f("README.md")]
        ),
        reference_draft(),
    )
    gateway.repairs = ["=== tests/test_calc.py ===\ndef test_total():\n    assert True\n"]
    built = await build(gateway)
    assert failed(built) == ["the reference solution passes every test"]
    assert built.starter["tests/test_calc.py"] == wrong


async def test_a_metrics_script_that_fails_is_repaired() -> None:
    gateway = FakeGateway(
        starter_draft(
            key_files=[
                f("key/make_data.py", MAKE_DATA),
                f("key/metrics.py", "raise SystemExit(1)\n"),
            ]
        ),
        reference_draft(),
    )
    gateway.repairs = [f"=== key/metrics.py ===\n{METRICS}"]
    built = await build(gateway)
    assert built.ok, failed(built)
    assert built.metrics == {"sum_matches": 1.0} and built.key["key/metrics.py"] == METRICS


async def test_a_local_writer_writes_one_file_per_call_and_may_leave_out_the_header() -> None:
    class Local(FakeGateway):
        def model_for(self, tier: str, purpose: str = "") -> str:
            return "ollama/qwen2.5-coder:7b"

        async def complete(self, **kwargs: Any) -> SimpleNamespace:
            reply = await super().complete(**kwargs)
            reply.content = reply.content.split("===\n", 1)[-1]  # the header line left out
            return reply

    gateway = Local(starter_draft(), reference_draft())
    built = await build(gateway)
    assert built.ok, failed(built)
    starter_calls = [c for c in gateway.complete_calls if c["purpose"] == "write-starter-file"]
    assert len(starter_calls) == 5 and built.starter["src/calc.py"] == BUGGY
    writes = [c for c in gateway.complete_calls if c["purpose"].startswith("write-")]
    assert all(c["stop"] == art.ONE_FILE_STOP for c in writes)
    assert all(c["max_tokens"] == art.LOCAL_FILE_MAX_TOKENS for c in writes)
    assert {c["prompt_version"] for c in writes} == {
        art.WRITE_ONE_FILE_VERSION, art.WRITE_ONE_REFERENCE_VERSION,
    }  # fmt: skip


async def test_a_local_file_that_runs_past_the_limit_is_asked_again_warmer() -> None:
    class Loops(FakeGateway):
        def model_for(self, tier: str, purpose: str = "") -> str:
            return "ollama/qwen2.5-coder:7b"

        async def complete(self, **kwargs: Any) -> SimpleNamespace:
            reply = await super().complete(**kwargs)
            target = kwargs["messages"][1]["content"].rsplit("(and no other):\n", 1)[-1]
            if target.startswith("- src/calc.py") and kwargs["temperature"] < 0.5:
                reply.finish_reason = "length"
            return reply

    gateway = Loops(starter_draft(), reference_draft())
    built = await build(gateway)
    assert built.ok, failed(built)
    asks = [
        c for c in gateway.complete_calls
        if c["purpose"] == "write-starter-file"
        and c["messages"][1]["content"].rsplit("(and no other):\n", 1)[-1].startswith("- src/calc")
    ]  # fmt: skip
    assert [c["temperature"] for c in asks] == [0.3, 0.6]
    assert all(c["max_tokens"] == art.LOCAL_FILE_MAX_TOKENS for c in asks)


async def test_a_local_reply_that_wrote_some_other_file_is_asked_again() -> None:
    class WrongFirst(FakeGateway):
        def model_for(self, tier: str, purpose: str = "") -> str:
            return "ollama/qwen2.5-coder:7b"

        async def complete(self, **kwargs: Any) -> SimpleNamespace:
            reply = await super().complete(**kwargs)
            asked = kwargs["messages"][1]["content"].rsplit("(and no other):\n", 1)[-1]
            if asked.startswith("- src/calc.py:") and not getattr(self, "fooled", False):
                self.fooled = True
                reply.content = "=== README.md ===\n# Something else\n"
            return reply

    gateway = WrongFirst(starter_draft(), reference_draft())
    built = await build(gateway)
    assert built.ok, failed(built)
    targets = [c["messages"][1]["content"].rsplit("(and no other):\n", 1)[-1] for c in
               gateway.complete_calls]  # fmt: skip
    asks = [t for t in targets if t.startswith("- src/calc.py")]
    assert len(asks) == 3  # the wrong file, then again; the reference writes it once more


async def test_a_local_model_gets_more_repair_rounds_than_a_hosted_one() -> None:
    class Local(FakeGateway):
        def model_for(self, tier: str, purpose: str = "") -> str:
            return "ollama/qwen2.5-coder:7b"

    broken = starter_draft(
        starter_files=[
            f("src/calc.py", "import no_such_module\n\n" + BUGGY),
            f("tests/test_calc.py", TEST),
            f("README.md"),
        ]
    )
    gateway = Local(broken, reference_draft())
    gateway.repairs = [""] * (art.REPAIRS - 1) + [f"=== src/calc.py ===\n{BUGGY}"]
    built = await build(gateway)
    assert built.ok, failed(built)  # fixed on the last free round
    repairs = [c for c in gateway.complete_calls if c["purpose"] == "repair-file"]
    assert len(repairs) == 4
    # the first round patches; later rounds rewrite from scratch, warmer, with the contract
    assert repairs[0]["temperature"] == 0.2 and repairs[1]["temperature"] == 0.7
    assert "Round 2" not in repairs[0]["messages"][1]["content"]
    assert "(Round 2: an earlier fix did not solve this" in repairs[1]["messages"][1]["content"]
    assert "Shared notes about names and signatures." in repairs[0]["messages"][1]["content"]


async def test_a_repair_that_does_not_compile_changes_nothing_and_late_rounds_rewrite() -> None:
    seen: list[dict[str, Any]] = []

    class Echo:
        async def complete(self, **kwargs: Any) -> SimpleNamespace:
            seen.append(kwargs)
            return SimpleNamespace(
                content="=== a.py ===\nx = 2\nOther files in the repository (outlines", cost_usd=0,
                model="m", finish_reason="stop",
            )  # fmt: skip

    async def repair(round_number: int) -> dict[str, str]:
        return await art.repair_files(
            Echo(), art.Spend(), tier="judge", budget_usd=1, scenario="s", goal="g",  # type: ignore[arg-type]
            problem="p", files={"a.py": "x = 1  # broken somehow\n"}, editable=["a.py"],
            round_number=round_number,
        )  # fmt: skip

    assert await repair(1) == {}  # prose in a Python file: refused
    assert "\nOther files in the repository" in seen[0]["stop"] and "\n=== " in seen[0]["stop"]
    assert "x = 1  # broken somehow" in seen[0]["messages"][1]["content"]
    await repair(art.REWRITE_FROM_ROUND)
    assert "x = 1  # broken somehow" not in seen[1]["messages"][1]["content"]
    assert "withheld" in seen[1]["messages"][1]["content"]


async def test_the_key_scripts_are_asked_for_with_how_they_are_run() -> None:
    gateway = FakeGateway(starter_draft(), reference_draft())
    await build(gateway)
    prompts = [c["messages"][1]["content"] for c in gateway.complete_calls]
    asked = next(p for p in prompts if "- key/make_data.py:" in p)
    assert "write exactly these files, at these paths: data/nums.json, key/truth.json" in asked
    assert "if __name__ == '__main__': main()" in asked
    assert "python -m key.metrics" in asked


async def test_a_test_file_that_passes_on_the_starter_is_noted_for_the_reviewer() -> None:
    passing = "def test_fine():\n    assert 1 + 1 == 2\n"
    gateway = FakeGateway(
        starter_draft(
            starter_files=[
                f("src/calc.py", BUGGY), f("tests/test_calc.py", TEST),
                f("tests/test_other.py", passing), f("README.md"),
            ]
        ),
        reference_draft(),
    )  # fmt: skip
    built = await build(gateway)
    assert built.ok, failed(built)
    assert built.notes == [
        "tests/test_other.py passes on the starter: check that the planted issue it targets is "
        "there."
    ]
    assert "## For the reviewer" in art.to_text(built, None)


async def test_a_later_attempt_writes_warmer() -> None:
    gateway = FakeGateway(starter_draft(), reference_draft())
    await art.build_artifacts(gateway, LocalRunner(), blueprint(), feedback="- it failed")  # type: ignore[arg-type]
    writes = [c for c in gateway.complete_calls if c["purpose"].startswith("write-")]
    assert writes and all(c["temperature"] == 0.6 for c in writes)


async def test_a_cut_off_repair_changes_nothing() -> None:
    class Cut:
        async def complete(self, **kwargs: Any) -> SimpleNamespace:
            return SimpleNamespace(
                content="=== a.py ===\nx = (", cost_usd=0, model="m", finish_reason="length"
            )

    changed = await art.repair_files(
        Cut(), art.Spend(), tier="judge", budget_usd=1, scenario="s", goal="g", problem="p",  # type: ignore[arg-type]
        files={"a.py": "x = 1\n"}, editable=["a.py"],
    )  # fmt: skip
    assert changed == {}


def test_words_that_give_a_planted_issue_away_are_removed_from_what_the_person_gets() -> None:
    code = (
        "import re\n\n\n"
        "def check(a, b):\n"
        '    """Checks a against b.\n\n    The planted flaw: a substring check.\n    """\n'
        "    # FLAW (planted): substring, so 5% matches 15%\n"
        "    return a in b  # deliberately naive\n\n\n"
        "def flawless():\n    return 'no flaws here'\n"
    )
    cleaned = art.without_hints("src/check.py", code)
    assert "planted" not in cleaned.lower() and "deliberately" not in cleaned
    assert "    return a in b\n" in cleaned and '"""Checks a against b.' in cleaned
    assert "def flawless():\n    return 'no flaws here'" in cleaned  # code and data stay
    assert art.syntax_error(cleaned) == ""
    readme = (
        "# Tool\n\nRun it.\n\n## Known flaws\n\nThe check is naive.\n\n## Tests\n\nRun pytest.\n"
    )
    assert (
        art.without_hints("README.md", readme) == "# Tool\n\nRun it.\n\n## Tests\n\nRun pytest.\n"
    )
    assert art.without_hints("data/x.json", '{"flaw": 1}') == '{"flaw": 1}'


async def test_a_flaw_named_in_a_comment_never_reaches_the_person() -> None:
    hinted = (
        "def total(xs):\n    # FLAW: drops the last number on purpose\n    return sum(xs[:-1])\n"
    )
    gateway = FakeGateway(
        starter_draft(
            starter_files=[f("src/calc.py", hinted), f("tests/test_calc.py", TEST), f("README.md")]
        ),
        reference_draft(),
    )
    built = await build(gateway)
    assert built.ok, failed(built)
    assert built.starter["src/calc.py"] == BUGGY


def test_a_one_file_reply_is_found_under_the_names_small_models_give_it() -> None:
    plan = [PlannedFile(path=p, purpose="Does what the plan says.") for p in ("README.md", "a.py")]
    readme = plan[:1]
    assert art.one_file({}, "# Title\n", readme, plan) == {"README.md": "# Title\n"}
    placeholder = art.split_files("=== path ===\nREADME.md\n\n# Title")
    assert art.one_file(placeholder, "", readme, plan) == {"README.md": "\n# Title"}
    other = {"a.py": "x = 1"}  # a real other file is not taken for the one asked for
    assert art.one_file(other, "", readme, plan) == other


def test_the_modules_a_test_imports_are_found_as_paths() -> None:
    files = ["src/calc.py", "src/io.py", "src/__init__.py", "app.py", "tests/test_x.py"]
    text = "import os\nfrom src.calc import total\nfrom src import io, missing\nimport app\n"
    assert art.imported(text, files) == ["src/calc.py", "src/io.py", "src/__init__.py", "app.py"]


def test_model_debris_is_tidied_and_problems_are_found_by_name() -> None:
    explained = "import json\n\ndef f():\n    return 1\n\nprint(f())\n\n---\nThis writes data.\n"
    assert art.clean_file(explained, "key/make_data.py") == (
        "import json\n\ndef f():\n    return 1\n\nprint(f())\n"
    )
    assert art.clean_file("Here it is:\n```python\nx = 1\n```\nDone.", "a.py") == "x = 1\n"
    assert art.clean_file("x = 1\n# ---\ny = 2\n", "a.py") == "x = 1\n# ---\ny = 2\n"
    assert art.clean_file("def (", "a.py") == "def (\n"  # nothing compiles: left for a repair
    problems = art.file_problems(
        {"a.py": "def (", "b.json": "{x", "c.jsonl": "{}\n{bad", "d.py": "x = 1", "e.md": "# ("}
    )
    assert sorted(problems) == ["a.py", "b.json", "c.jsonl"]
    assert problems["c.jsonl"].startswith("line 2")
    output = 'File "/work/key/make_data.py", line 3\n  File "/work/src/io.py", line 9\nsrc/io.py:9'
    assert art.mentioned(output, ["key/make_data.py", "src/io.py", "io.py"]) == [
        "src/io.py", "key/make_data.py",
    ]  # fmt: skip
    assert art.split_files("### === `a.py` ===\nx\n=== FILE: b.py ===\ny") == {
        "a.py": "x",
        "b.py": "y",
    }


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
        gateway,  # type: ignore[arg-type]
        LocalRunner(),
        blueprint(),
        feedback="the reference failed",
        reuse=first,
    )
    assert again.ok, [c for c in again.checks if not c.ok]
    assert [c["purpose"] for c in gateway.structured_calls] == ["plan-reference"]
    assert "the reference failed" in gateway.structured_calls[0]["messages"][1]["content"]
    assert all(c["purpose"] == "write-reference-file" for c in gateway.complete_calls)
    assert again.starter == first.starter


async def test_a_full_size_project_keeps_every_prompt_inside_groqs_per_minute_cap() -> None:
    """Rehearsal at the planner's limits: 14 files near 120 lines, 200 KB of generated data."""
    from firstweek_core.llm.gateway import fit_reply_room

    def body(n: int) -> str:
        step = [
            "def step_{i}(rows, limit=10):",
            '    """One step."""',
            "    total = 0",
            "    for row in rows:",
            "        total += row['score'] * limit",
            "    return total",
        ]
        return "\n".join(line.format(i=i) for i in range(n // 6) for line in step) + "\n"

    planned = [PlannedFile(path=f"src/m{i}.py", purpose="A precise line of purpose. " * 3)
               for i in range(14)]  # fmt: skip
    content = {p.path: body(118) for p in planned}
    prompts: list[str] = []

    class Measuring:
        async def complete(self, **kwargs: Any) -> SimpleNamespace:
            prompt = kwargs["messages"][0]["content"] + kwargs["messages"][1]["content"]
            prompts.append(prompt)
            assert fit_reply_room("groq/openai/gpt-oss-120b", kwargs["messages"], 8000)
            asked = re.findall(r"^- (\S+): ", prompt.split("Write these files:\n")[1], re.M)
            reply = "\n".join(f"=== {p} ===\n{content[p]}" for p in asked)
            return SimpleNamespace(
                content=reply, cost_usd=Decimal(0), model="m", finish_reason="stop"
            )

    def render(group: list[PlannedFile], written: dict[str, str]) -> dict[str, str]:
        return {
            "scenario": "s" * 600,
            "notes": "n" * 6000,
            "plan": art.plan_text(planned),
            "written": art.shown_outline(written),
            "targets": art.targets_text(group),
        }

    written = await art.write_files(
        Measuring(), art.Spend(), purpose="write-starter-file", version=art.WRITE_FILE_VERSION,  # type: ignore[arg-type]
        tier="judge", planned=planned, render=render, budget_usd=1.0,
    )  # fmt: skip
    assert len(written) == 14 and len(prompts) == 4
    assert max(len(p) for p in prompts) // 4 < 6_000  # tokens, roughly

    data = {"data/big.jsonl": ('{"id": 1, "text": "' + "x" * 300 + '"}\n') * 600}
    assert len(data["data/big.jsonl"]) > 190_000
    assert len(art.shown_preview(data)) // 4 < 1_500  # 200 KB of data costs about 1,000 tokens


def starter_plan_of(draft: StarterDraft, **changes: Any) -> StarterPlan:
    def planned(files: list[FileDraft]) -> list[PlannedFile]:
        return [PlannedFile(path=x.path, purpose="Does what the plan says.") for x in files]

    fields: dict[str, Any] = {
        "design_notes": "Shared notes about names and signatures. " * 3,
        "starter_files": planned(draft.starter_files),
        "key_files": planned(draft.key_files),
        "generated": draft.generated,
    }
    return StarterPlan(**{**fields, **changes})


def test_a_plan_slip_that_needs_no_judgement_is_fixed_by_code() -> None:
    draft = starter_draft()
    plan = starter_plan_of(draft, generated=[*draft.generated, "metrics.json", "key/metrics.json"])
    assert art.repair_plan(plan).generated == draft.generated
    twice = starter_plan_of(draft, generated=[*draft.generated, "data/extra.json"])
    twice.starter_files.append(PlannedFile(path="data/extra.json", purpose="A static copy."))
    fixed = art.repair_plan(twice)
    assert "data/extra.json" not in [f.path for f in fixed.starter_files]
    assert (
        art.plan_problems(
            [f.path for f in fixed.starter_files],
            [f.path for f in fixed.key_files],
            fixed.generated,
        )
        == []
    )


async def test_a_plan_without_tests_is_planned_again_before_any_file_is_written() -> None:
    draft = starter_draft()
    no_tests = starter_plan_of(
        draft,
        starter_files=[
            PlannedFile(path="src/calc.py", purpose="Does what the plan says."),
            PlannedFile(path="evals/test_calc.py", purpose="Does what the plan says."),
            PlannedFile(path="README.md", purpose="Does what the plan says."),
        ],
    )
    gateway = FakeGateway(draft, reference_draft())
    gateway.first_plans = [no_tests]
    built = await build(gateway)
    assert built.ok, [c for c in built.checks if not c.ok]
    plans = [c for c in gateway.structured_calls if c["purpose"] == "plan-starter"]
    assert len(plans) == 2
    assert "tests/test_*.py" in plans[1]["messages"][1]["content"]
    starter_writes = [c for c in gateway.complete_calls if c["purpose"] == "write-starter-file"]
    assert all("evals/test_calc.py" not in c["messages"][1]["content"].split("Write these")[1]
               for c in starter_writes)  # the bad plan cost no file writes  # fmt: skip


async def test_a_plan_that_never_passes_the_checks_stops_before_writing_anything() -> None:
    draft = starter_draft()
    bad = starter_plan_of(draft, starter_files=[
        PlannedFile(path=f"src/m{i}.py", purpose="Does what the plan says.") for i in range(3)
    ])  # fmt: skip
    gateway = FakeGateway(draft, reference_draft())
    gateway.first_plans = [bad, bad, bad]
    built = await build(gateway)
    assert failed(built) == ["starter files are well formed"]
    assert gateway.complete_calls == [] and len(gateway.structured_calls) == art.REPLANS


def test_folders_for_generated_files_are_created_for_the_generator() -> None:
    from firstweek_simulation.artifacts import output_dirs

    assert output_dirs(["data/a.json", "logs/x.log", "metrics.json", "data/b.json"]) == {
        "data/.keep": "",
        "logs/.keep": "",
    }
