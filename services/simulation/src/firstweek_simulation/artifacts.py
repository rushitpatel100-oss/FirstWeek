"""Starter repository, dataset and reference solution for a blueprint (ADR 0019).

Models write the files; code runs them in the sandbox and records what happened. Every
number in the answer key's metrics comes from running the reference solution, never from a
model's guess. This module builds and measures; the validation gate (next step) decides what
is acceptable and regenerates."""

import ast
import builtins
import io
import json
import re
import shutil
import sys
import tokenize
import typing
import uuid
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

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
from firstweek_core.llm import LLMGateway, StructuredOutputError
from firstweek_core.llm import Tier as ModelTier
from firstweek_core.sandbox import JobResult, SandboxJob, SandboxRunner
from firstweek_simulation.blueprint import BlueprintError, load_prompt

PLAN_STARTER_VERSION = "plan-starter.v4"
REPLANS = 3  # tries at a plan that passes the checks, before any file is written
WRITE_FILE_VERSION = "write-files.v1"
PLAN_REFERENCE_VERSION = "plan-reference.v2"
WRITE_REFERENCE_VERSION = "write-reference-files.v1"
# A model on this machine writes one file per call, stopped at the next file's header line:
# small models otherwise write out the whole repository on every call.
WRITE_ONE_FILE_VERSION = "write-one-file.v1"
WRITE_ONE_REFERENCE_VERSION = "write-one-reference-file.v1"
LOCAL_FILE_MAX_TOKENS = 4000
ONE_FILE_STOP = ["\n=== "]
WRONG_FILE_RETRIES = 2  # a single-file reply that wrote some other file is asked again
PLAN_MAX_TOKENS = 12000
FILE_MAX_TOKENS = 8000
FILE_MAX_TOKENS_CEILING = 16000
BATCH_FILES = 4  # files per model call; a cut-off batch is split in half and retried
LOCAL_BATCH_FILES = 1  # a model on this machine writes one file per call: calls are free, and a
# small model keeps its context window and its attention on one file
REPAIRS = 6  # fix-and-run-again rounds per check with a local model, where calls are free
HOSTED_REPAIRS = 1  # with hosted free models only: one round, so the daily quota lasts
REPAIR_VERSION = "repair-files.v1"
REPAIR_MAX_TOKENS = 6000
REPAIR_FILES = 3  # files shown in full, and allowed to change, in one repair call
REWRITE_FROM_ROUND = 4  # from this round the broken file is withheld: written fresh, not patched
# With a local model, this round goes to a hosted model first (purpose "repair-hard", not in
# MODEL_LOCAL_PURPOSES): a small model often cannot see the bug it wrote itself, and one hosted
# call per failing check costs little quota. Without hosted quota it falls back to the local one.
HOSTED_ROUND = 3
# A small model sometimes runs on into the prompt's own headings; stop it there.
REPAIR_STOP = ["\nOther files in the repository", "\nWhat went wrong:", "\nFiles you may change"]
FENCE = re.compile(r"^\s*```[\w+-]*\s*$")
LAMBDA_RAISE = re.compile(r"^([ \t]*)(\w+)\s*=\s*lambda\b([^:\n]*):\s*raise\s+(.+)$", re.M)
HINT = re.compile(r"\b(?:planted|flaws?|flawed|deliberate(?:ly)?|intentional(?:ly)?)\b", re.I)
SEPARATOR = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,}|\*\*.*\*\*:?)\s*$")  # never Python
DATA_PREVIEW_LINES = 12  # data files appear in prompts as their first lines only
OUTLINE_FULL_LINES = 40  # shorter code files appear whole in a writer's context
STARTER_CHECKS = (
    "starter files are well formed",
    "the data generator runs and writes every file it lists",
    "the starter runs and fails its target tests",
)
ALLOWED_SUFFIXES = {
    ".py", ".md", ".txt", ".json", ".jsonl", ".csv", ".log",
    ".toml", ".cfg", ".ini", ".yaml", ".yml",
}  # fmt: skip
KEY_DIR = "key"
GENERATOR = f"{KEY_DIR}/make_data.py"
METRICS_SCRIPT = f"{KEY_DIR}/metrics.py"
# `-o addopts=` ignores options a written config file adds (`--flake8`, `--cov`): plugins the
# sandbox does not have would stop pytest before any test runs.
TEST_COMMAND = ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "-o", "addopts="]
# Config files a model may plan that change how pytest or a linter runs: never written.
CONFIG_FILES = {"pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml", ".flake8", "mypy.ini"}
# Packages the sandbox image has besides the standard library (infra/docker/sandbox.Dockerfile).
SANDBOX_PACKAGES = {
    "numpy", "pandas", "pytest", "_pytest", "requests", "urllib3", "idna", "certifi",
    "charset_normalizer", "dateutil", "pytz", "tzdata", "six",
}  # fmt: skip
DATA_PREVIEW_CHARS = 1500  # a dataset written as one long line must not fill a prompt
DATA_PREVIEW_LINE_CHARS = 300
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
    notes: list[str] = field(default_factory=list)  # for the reviewer; they do not gate
    calls: dict[str, int] = field(default_factory=dict)  # model -> calls this build made
    design_notes: str = ""  # the starter plan's contract, kept for a later attempt's repairs

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    @property
    def starter_ok(self) -> bool:
        """The starter passed every check, so a retry can keep it and redo only the solution."""
        passed = {c.name for c in self.checks if c.ok}
        return all(name in passed for name in STARTER_CHECKS) and bool(self.starter)


def is_key_path(path: str) -> bool:
    return PurePosixPath(path).parts[0] == KEY_DIR


def plan_problems(starter: list[str], key: list[str], generated: list[str]) -> list[str]:
    """What is wrong with a set of paths. Checked on the plan, before any file is written."""
    problems: list[str] = []
    every = [*starter, *key, *generated]
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
        problems.append(
            "The starter needs target tests as files named tests/test_*.py in the tests/ folder "
            "at the repository root, whatever path the tickets mention."
        )
    clash = sorted(set(generated) & set(starter + key))
    if clash:
        problems.append(f"Generated files are also written as files: {clash}.")
    if not any(not is_key_path(p) for p in generated):
        problems.append("make_data.py must write at least one file the person receives.")
    return problems


def starter_problems(draft: StarterDraft) -> list[str]:
    """What is wrong with the files before anything runs."""
    return plan_problems(
        [f.path for f in draft.starter_files], [f.path for f in draft.key_files], draft.generated
    )


def repair_plan(plan: StarterPlan) -> StarterPlan:
    """Fixes by code the plan slips that need no judgement.

    `metrics.json` is what key/metrics.py writes, not what make_data.py writes, so it is not a
    generated file. A path both written as a file and generated is generated, so it is not also
    written. Config files (pytest.ini, setup.cfg, pyproject.toml, ...) are dropped: a model's
    `addopts = --flake8` stops pytest before any test runs."""
    generated = [g for g in plan.generated if g not in ("metrics.json", f"{KEY_DIR}/metrics.json")]
    taken = set(generated)

    def keep(path: str) -> bool:
        return path not in taken and PurePosixPath(path).name not in CONFIG_FILES

    return plan.model_copy(
        update={
            "generated": generated or plan.generated,
            "starter_files": [f for f in plan.starter_files if keep(f.path)],
            "key_files": [f for f in plan.key_files if keep(f.path)],
        }
    )


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


def clean_file(text: str, path: str = "") -> str:
    """The file as written, without a surrounding code fence, and for Python without the
    debris a model leaves around the code (fences, a separator and an explanation)."""
    body = text.strip("\n")
    lines = body.splitlines()
    if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
        body = "\n".join(lines[1:-1])
    body = body.rstrip() + "\n"
    if path.endswith(".py"):
        return add_missing_imports(tidy_python(body))
    if path.endswith((".json", ".jsonl", ".csv")):
        return "\n".join(line for line in body.splitlines() if not FENCE.match(line)) + "\n"
    return body


def syntax_error(text: str, path: str = "<file>") -> str:
    """'' if the text is valid Python, else the error. Compiling checks syntax and runs nothing."""
    try:
        compile(text, path, "exec", dont_inherit=True)
    except SyntaxError as exc:
        line = (exc.text or "").strip()
        shown = f": `{line}`" if line else ""
        hint = (
            " (a lambda cannot contain a statement such as raise: use a def)"
            if re.search(r"\blambda\b[^:]*:\s*(raise|return|yield|assert)\b", line)
            else ""
        )
        return f"line {exc.lineno}: {exc.msg}{shown}{hint}"
    except ValueError as exc:  # null bytes
        return str(exc)
    return ""


def tidy_python(text: str) -> str:
    """Valid Python as it is; otherwise the first cleaned-up version that compiles: without
    fence lines, then cut at the first fence or separator line after the code started (a model
    often ends a file with `---` and an explanation). Unchanged if nothing compiles."""
    if not syntax_error(text):
        return text
    text = LAMBDA_RAISE.sub(
        lambda m: f"{m[1]}def {m[2]}({m[3].strip()}):\n{m[1]}    raise {m[4]}", text
    )  # `f = lambda x: raise E()` is a slip small models make often: as a def it is valid
    if not syntax_error(text):
        return text
    lines = text.splitlines()
    candidates = ["\n".join(line for line in lines if not FENCE.match(line))]
    started = False
    for i, line in enumerate(lines):
        if FENCE.match(line) or SEPARATOR.match(line):
            if started and i * 2 >= len(lines):  # an explanation after the code, not before it
                candidates.append("\n".join(x for x in lines[:i] if not FENCE.match(x)))
                break
        elif line.strip():
            started = True
    fenced = re.search(r"^\s*```[\w+-]*\s*\n(.*?)^\s*```\s*$", text, flags=re.M | re.S)
    if fenced:
        candidates.append(fenced.group(1))
    for candidate in candidates:
        if candidate.strip() and not syntax_error(candidate):
            return candidate.rstrip() + "\n"
    return text


def without_hints(path: str, text: str) -> str:
    """The file without words that give a planted issue away: comments and docstring lines in
    Python, lines and whole sections in Markdown. The person has to find the issue; models
    often write `# FLAW: ...` or a README section on the flaws however they are asked."""
    if not HINT.search(text):
        return text
    if path.endswith(".py"):
        return _python_without_hints(text)
    if path.endswith((".md", ".txt", ".rst")):
        return _prose_without_hints(text)
    return text


def _python_without_hints(text: str) -> str:
    if syntax_error(text):
        return text
    lines = text.splitlines(keepends=True)
    drop: set[int] = set()
    cut: dict[int, int] = {}
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if not HINT.search(token.string):
                continue
            row, col = token.start
            if token.type == tokenize.COMMENT:
                if lines[row - 1][:col].strip():
                    cut[row - 1] = col  # an inline comment: keep the code before it
                else:
                    drop.add(row - 1)
            elif token.type == tokenize.STRING and token.end[0] > row:
                # inner lines of a multi-line string (a docstring), not the lines with quotes
                drop.update(i for i in range(row, token.end[0] - 1) if HINT.search(lines[i]))
    except (tokenize.TokenError, SyntaxError):
        return text
    kept = [
        (line[: cut[i]].rstrip() + "\n") if i in cut else line
        for i, line in enumerate(lines)
        if i not in drop
    ]
    result = "".join(kept)
    return result if not syntax_error(result) else text


def _prose_without_hints(text: str) -> str:
    kept: list[str] = []
    skipping_level = 0  # inside a section whose heading gives an issue away
    for line in text.splitlines():
        heading = re.match(r"^(#+)\s", line)
        if heading and skipping_level and len(heading.group(1)) <= skipping_level:
            skipping_level = 0
        if skipping_level:
            continue
        if heading and HINT.search(line):
            skipping_level = len(heading.group(1))
            continue
        if not HINT.search(line):
            kept.append(line)
    return "\n".join(kept).rstrip() + "\n"


def _optional_imports(tree: ast.AST) -> set[int]:
    """ids of import nodes inside `try: ... except ImportError`: optional, so allowed."""
    found: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Try) and any(
            isinstance(h.type, ast.Name) and h.type.id in ("ImportError", "ModuleNotFoundError")
            for h in node.handlers
        ):
            found.update(id(n) for b in node.body for n in ast.walk(b))
    return found


def missing_packages(files: dict[str, str]) -> dict[str, list[str]]:
    """Python files that import a package the sandbox does not have (only the standard
    library and SANDBOX_PACKAGES are there, and no network to install more)."""
    local = {PurePosixPath(p).parts[0].removesuffix(".py") for p in files}
    out: dict[str, list[str]] = {}
    for path, text in files.items():
        if not path.endswith(".py"):
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        optional = _optional_imports(tree)
        names: set[str] = set()
        for node in ast.walk(tree):
            if id(node) in optional:
                continue
            if isinstance(node, ast.Import):
                names |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
        missing = sorted(
            n for n in names
            if n not in sys.stdlib_module_names and n not in SANDBOX_PACKAGES and n not in local
        )  # fmt: skip
        if missing:
            out[path] = missing
    return out


COMMON_MODULES = {
    "json", "os", "re", "sys", "time", "math", "random", "datetime", "pathlib", "itertools",
    "functools", "collections", "statistics", "csv", "logging", "argparse", "dataclasses",
    "hashlib", "uuid", "string", "textwrap", "copy", "enum", "abc", "asyncio", "heapq",
    "bisect", "decimal", "fractions", "operator", "pprint", "tempfile", "shutil", "glob",
    "unittest", "inspect", "warnings", "contextlib", "threading", "queue", "secrets", "base64",
}  # fmt: skip


def add_missing_imports(text: str) -> str:
    """Adds the imports a model forgot: a typing name (`List`, `Optional`) or a common standard
    library module (`random`, `json`) that the file uses but never imports or defines. Small
    models forget these all the time, and a NameError at import stops every test."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return text
    bound: set[str] = set(dir(builtins))
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            bound |= {(a.asname or a.name).split(".")[0] for a in node.names}
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            bound.add(node.name)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, ast.Global | ast.Nonlocal):
            bound |= set(node.names)
        elif isinstance(node, ast.MatchAs | ast.MatchStar) and node.name:
            bound.add(node.name)
        elif isinstance(node, ast.Name):
            (used if isinstance(node.ctx, ast.Load) else bound).add(node.id)
    missing = used - bound
    typing_names = sorted(n for n in missing if n in typing.__all__)
    modules = sorted(n for n in missing if n in COMMON_MODULES)
    if not typing_names and not modules:
        return text
    added = [f"import {m}" for m in modules]
    if typing_names:
        added.append(f"from typing import {', '.join(typing_names)}")
    # after a module docstring and `from __future__` imports, before everything else
    at = 0
    for statement in tree.body:
        is_docstring = (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        )
        is_future = isinstance(statement, ast.ImportFrom) and statement.module == "__future__"
        if not (is_docstring or is_future):
            break
        at = statement.end_lineno or at
    lines = text.splitlines()
    result = "\n".join([*lines[:at], *added, *lines[at:]]) + "\n"
    return result if not syntax_error(result) else text


def file_problems(files: dict[str, str]) -> dict[str, str]:
    """Files that cannot be valid as written: Python that does not compile, JSON that does not
    parse. Found before anything runs, so a repair can be asked for by name."""
    out: dict[str, str] = {}
    for path, text in files.items():
        if path.endswith(".py"):
            if error := syntax_error(text, path):
                out[path] = f"not valid Python ({error})"
        elif path.endswith(".json") and text.strip():
            try:
                json.loads(text)
            except ValueError as exc:
                out[path] = f"not valid JSON ({exc})"
        elif path.endswith(".jsonl"):
            for number, line in enumerate(text.splitlines(), 1):
                try:
                    if line.strip():
                        json.loads(line)
                except ValueError as exc:
                    out[path] = f"line {number} is not valid JSON ({exc})"
                    break
    return out


def mentioned(output: str, paths: Iterable[str]) -> list[str]:
    """Repository files named in an error or test output, latest mention first: the innermost
    frame of a traceback is usually where the fault is."""
    hits: list[tuple[int, int, str]] = []
    for path in paths:
        for found in re.finditer(re.escape(path), output):
            before = output[found.start() - 1] if found.start() else " "
            after = output[found.end()] if found.end() < len(output) else " "
            if not (before.isalnum() or before in "_.-") and not (after.isalnum() or after == "_"):
                hits.append((found.start(), found.end(), path))
    # "io.py" inside "src/io.py" is the longer path's mention, not its own
    own = [h for h in hits if not any(o[0] < h[0] and o[1] == h[1] for o in hits)]
    last: dict[str, int] = {}
    for start, _, path in own:
        last[path] = max(start, last.get(path, -1))
    return sorted(last, key=lambda p: -last[p])


@dataclass
class Spend:
    cost_usd: float = 0.0
    model: str = ""
    calls: Counter[str] = field(default_factory=Counter)  # model -> calls, for the report

    def add(self, cost_usd: object, model: str) -> None:
        self.cost_usd += float(cost_usd)  # type: ignore[arg-type]
        self.model = model
        self.calls[model] += 1


def split_files(text: str) -> dict[str, str]:
    """Files from a reply where each starts with a line `=== path ===`."""
    out: dict[str, str] = {}
    current: str | None = None
    body: list[str] = []
    for line in text.splitlines():
        found = re.fullmatch(
            r"\s*(?:#+\s*)?={3,}\s*(?:file:\s*)?`?([\w./-]+?)`?\s*={3,}\s*", line, flags=re.I
        )
        if found:
            if current is not None:
                out[current] = "\n".join(body)
            current, body = found.group(1), []
        elif current is not None:
            body.append(line)
    if current is not None:
        out[current] = "\n".join(body)
    return out


async def write_files(
    gateway: LLMGateway,
    spend: Spend,
    *,
    purpose: str,
    version: str,
    tier: ModelTier,
    planned: list[PlannedFile],
    render: Callable[[list[PlannedFile], dict[str, str]], dict[str, str]],
    budget_usd: float,
    batch: int = BATCH_FILES,
    max_tokens: int = FILE_MAX_TOKENS,
    stop: list[str] | None = None,
    temperature: float = 0.3,
) -> dict[str, str]:
    """A few files per model call, in order, each call seeing outlines of the files before it.

    A cut-off reply is split in half and retried; a single file gets one retry at twice the
    room; a file the reply left out is asked for on its own.

    One file at a time (`stop` set, a local model): a file under 150 lines that runs past the
    limit is a model repeating itself, not a long file, and a reply that wrote some other file
    missed the point. Either is asked again at the same limit, warmer, up to WRONG_FILE_RETRIES
    times."""
    system, user = load_prompt(version)
    written: dict[str, str] = {}
    misses: dict[str, int] = {}
    queue = [planned[i : i + batch] for i in range(0, len(planned), batch)]
    while queue:
        group = queue.pop(0)
        limit = max_tokens
        while True:
            result = await gateway.complete(
                purpose=purpose,
                messages=[
                    {"role": "system", "content": system},
                    {
                        "role": "user",
                        "content": user.format(
                            **render(group, written), header=f"=== {group[0].path} ==="
                        ),
                    },
                ],
                tier=tier,
                max_tokens=limit,
                temperature=min(1.0, temperature + 0.3 * misses.get(group[0].path, 0)),
                budget_scope="build-artifacts",
                budget_usd=budget_usd,
                prompt_version=version,
                stop=stop,
            )
            spend.add(result.cost_usd, result.model)
            if result.finish_reason != "length" or len(group) > 1 or stop is not None:
                break
            ceiling = max(FILE_MAX_TOKENS_CEILING, max_tokens) if stop is None else 2 * max_tokens
            if limit >= ceiling:
                raise FileWriteError(f"{group[0].path}: the reply was cut off at {limit} tokens")
            limit = min(limit * 2, ceiling)  # thinking may have used the room
        if result.finish_reason == "length" and len(group) == 1:  # one file, a looping model
            path = group[0].path
            misses[path] = misses.get(path, 0) + 1
            if misses[path] > WRONG_FILE_RETRIES:
                raise FileWriteError(f"{path}: the reply was cut off at {limit} tokens")
            queue.insert(0, group)
            continue
        if result.finish_reason == "length":
            half = len(group) // 2
            queue[:0] = [group[:half], group[half:]]
            continue
        files = one_file(split_files(result.content), result.content, group, planned)
        missing: list[PlannedFile] = []
        for item in group:
            text = files.get(item.path, "")
            if text.strip():
                written[item.path] = clean_file(text, item.path)
            elif PurePosixPath(item.path).name == "__init__.py":
                written[item.path] = ""  # an empty package marker is a valid file
            else:
                missing.append(item)
        if missing and len(group) == 1:
            path = group[0].path
            misses[path] = misses.get(path, 0) + 1
            if stop is None or misses[path] > WRONG_FILE_RETRIES:
                raise FileWriteError(f"{path}: the reply was empty")
        queue[:0] = [[item] for item in missing]
    return written


def one_file(
    files: dict[str, str], reply: str, group: list[PlannedFile], planned: list[PlannedFile]
) -> dict[str, str]:
    """For a one-file request, the file under the names small models give it: no header at
    all, or a placeholder header (`=== path ===`) with the real path on the next line."""
    if len(group) != 1 or group[0].path in files:
        return files
    target = group[0].path
    if not files:
        return {target: reply} if reply.strip() else {}
    known = {item.path for item in planned}
    if len(files) == 1 and not set(files) & known:
        lines = next(iter(files.values())).lstrip("\n").splitlines()
        if lines and lines[0].strip().strip("`*") == target:
            lines = lines[1:]
        return {target: "\n".join(lines)}
    return files


def is_data(path: str) -> bool:
    return PurePosixPath(path).suffix not in {".py", ".md", ".toml", ".cfg", ".ini"}


def preview(path: str, text: str) -> str:
    """Data files as their first lines, each and all cut short: enough to see the format, not
    the whole dataset. A JSON file written as one long line is one line of any length."""
    if not is_data(path):
        return text
    lines = text.splitlines()
    kept = [
        line if len(line) <= DATA_PREVIEW_LINE_CHARS else line[:DATA_PREVIEW_LINE_CHARS] + " ..."
        for line in lines[:DATA_PREVIEW_LINES]
    ]
    shown_text = "\n".join(kept)[:DATA_PREVIEW_CHARS]
    if shown_text == text:
        return text
    return shown_text + f"\n... ({len(lines)} lines, {len(text)} characters in all)"


def outline(path: str, text: str) -> str:
    """A long code file as its imports, signatures, first docstring lines and constants."""
    lines = text.splitlines()
    if not path.endswith(".py") or len(lines) <= OUTLINE_FULL_LINES:
        return preview(path, text)
    kept: list[str] = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if re.match(r"(import |from |class |def |async def |@|[A-Z_][A-Z0-9_]* *=)", stripped):
            kept.append(line)
            after = lines[i + 1].strip() if i + 1 < len(lines) else ""
            if stripped.startswith(("def ", "async def ", "class ")) and after.startswith('"""'):
                kept.append(lines[i + 1])
    return "\n".join(kept) + "\n# (outline: bodies left out)"


def shown_outline(files: dict[str, str]) -> str:
    return (
        "\n\n".join(f"=== {p} ===\n{outline(p, c)}" for p, c in sorted(files.items()))
        or "(none yet)"
    )


REPAIR_CONTEXT_CHARS = 12_000  # outlines of other files in a repair prompt, at most


def related_outline(others: dict[str, str], allowed: list[str], files: dict[str, str]) -> str:
    """Outlines of the other files for a repair, the most related first (modules the repaired
    files import, then files that import them), within REPAIR_CONTEXT_CHARS; past that, only
    names. A repair prompt has to fit a local model's context window, or it goes to a hosted
    model and spends the daily quota."""
    imports = {m for a in allowed for m in imported(files.get(a, ""), files)}
    stems = {PurePosixPath(a).with_suffix("").as_posix().replace("/", ".") for a in allowed}
    importers = {p for p, t in others.items() if any(stem in t for stem in stems)}
    order = sorted(others, key=lambda p: (p not in imports, p not in importers, is_data(p), p))
    parts: list[str] = []
    used = 0
    left: list[str] = []
    for path in order:
        block = f"=== {path} ===\n{outline(path, others[path])}"
        if used + len(block) > REPAIR_CONTEXT_CHARS:
            left.append(path)
            continue
        parts.append(block)
        used += len(block)
    if left:
        parts.append("Also in the repository (not shown): " + ", ".join(left))
    return "\n\n".join(parts) or "(none)"


def shown_preview(files: dict[str, str]) -> str:
    return (
        "\n\n".join(f"=== {p} ===\n{preview(p, c)}" for p, c in sorted(files.items()))
        or "(none yet)"
    )


def targets_text(group: list[PlannedFile]) -> str:
    return "\n".join(f"- {i.path}: {i.purpose}" for i in group)


def shown(files: dict[str, str]) -> str:
    return "\n\n".join(f"=== {p} ===\n{c}" for p, c in sorted(files.items())) or "(none yet)"


def plan_text(items: list[PlannedFile]) -> str:
    return "\n".join(f"- {i.path}: {i.purpose}" for i in items)


def output_dirs(generated: list[str]) -> dict[str, str]:
    """An empty placeholder in each folder the generator writes to, so the folder exists: models
    often forget to create it, and the generator then fails on a missing `data/`."""
    return {f"{path.rsplit('/', 1)[0]}/.keep": "" for path in generated if "/" in path}


def with_key_contracts(items: list[PlannedFile], generated: list[str]) -> list[PlannedFile]:
    """The two key scripts with how they are run spelled out: the generator was the file small
    models got wrong most often (no main block, wrong paths, folders not made)."""
    rules = {
        GENERATOR: (
            " It runs as `python -m key.make_data --seed N` from the repository root and must "
            f"write exactly these files, at these paths: {', '.join(generated)}. Structure: a "
            "main() that parses --seed (int) with argparse, makes rng = random.Random(seed), "
            "creates each folder it writes into (os.makedirs(..., exist_ok=True)) and writes every "
            "file; the file ends with `if __name__ == '__main__': main()`."
        ),
        METRICS_SCRIPT: (
            " It runs as `python -m key.metrics` from the repository root and writes metrics.json "
            "there: one flat JSON object of numbers. Structure: a main() that computes and writes "
            "it; the file ends with `if __name__ == '__main__': main()`."
        ),
    }
    return [
        i.model_copy(update={"purpose": i.purpose + rules[i.path]}) if i.path in rules else i
        for i in items
    ]


def local_writing(local: bool) -> dict[str, Any]:
    """How files are asked for: one at a time, small and stopped at the next header for a model
    on this machine; a few per call for hosted models, whose requests are counted."""
    if not local:
        return {"batch": BATCH_FILES}
    return {"batch": LOCAL_BATCH_FILES, "max_tokens": LOCAL_FILE_MAX_TOKENS, "stop": ONE_FILE_STOP}


def writer_is_local(gateway: LLMGateway, tier: ModelTier, purpose: str) -> bool:
    """Whether this call goes first to a model on this machine, where calls cost nothing."""
    model_for = getattr(gateway, "model_for", None)
    return model_for is not None and str(model_for(tier, purpose)).startswith("ollama/")


async def repair_files(
    gateway: LLMGateway,
    spend: Spend,
    *,
    tier: ModelTier,
    budget_usd: float,
    scenario: str,
    goal: str,
    problem: str,
    files: dict[str, str],
    editable: list[str],
    round_number: int = 1,
    hard: bool = False,
) -> dict[str, str]:
    """One model call that rewrites whichever of the first few `editable` files the problem
    needs. Returns only files it was allowed to change, cleaned; a cut-off reply changes
    nothing, so a half-written file never replaces a whole one.

    From the second round on, the writer is told the earlier fix did not work and to rewrite
    simply from scratch, at a higher temperature: asked the same way, a small model gives the
    same broken answer again."""
    allowed = list(dict.fromkeys(editable))[:REPAIR_FILES]
    rewrite = round_number >= REWRITE_FROM_ROUND and not hard
    if round_number > 1:
        problem = (
            f"(Round {round_number}: an earlier fix did not solve this. Do not repeat it: "
            "rewrite the file from scratch, simply and correctly, from the goal and the plan.)\n"
            + problem
        )
    if not allowed:
        return {}
    system, user = load_prompt(REPAIR_VERSION)
    others = {p: t for p, t in files.items() if p not in allowed}
    result = await gateway.complete(
        purpose="repair-hard" if hard else "repair-file",
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": user.format(
                    scenario=scenario,
                    goal=goal,
                    problem=tail(problem, 40),
                    editable="\n\n".join(
                        f"=== {p} ===\n"
                        + (
                            "(the broken version is withheld: write this file again from scratch)"
                            if rewrite and not p.startswith("tests/")  # tests stay: they are
                            else files.get(p, "")  # the spec, and a wrong one is corrected
                        )
                        for p in allowed
                    ),
                    others=related_outline(others, allowed, files),
                ),
            },
        ],
        tier=tier,
        max_tokens=REPAIR_MAX_TOKENS,
        temperature=0.2 if round_number == 1 else 0.7,
        budget_scope="build-artifacts",
        budget_usd=budget_usd,
        prompt_version=REPAIR_VERSION,
        stop=REPAIR_STOP + (ONE_FILE_STOP if len(allowed) == 1 else []),
    )
    spend.add(result.cost_usd, result.model)
    if result.finish_reason == "length":
        return {}
    replies = split_files(result.content)
    if not replies and len(allowed) == 1 and result.content.strip():
        replies = {allowed[0]: result.content}  # one file, written without its header line
    cleaned = {p: clean_file(t, p) for p, t in replies.items() if p in allowed and t.strip()}
    # A repair that does not even compile or parse never replaces what is there.
    broken = file_problems(cleaned)
    return {p: t for p, t in cleaned.items() if p not in broken}


def imported(text: str, paths: Iterable[str]) -> list[str]:
    """Repository modules a file imports, as paths: where a failing assertion in a test points
    when its traceback names only the test."""
    known, out = set(paths), []
    pattern = r"^\s*(?:from\s+([\w.]+)\s+import\s+\(?([\w, ]+)|import\s+([\w.]+))"
    for found in re.finditer(pattern, text, flags=re.M):
        module = (found.group(1) or found.group(3)).replace(".", "/")
        candidates = [f"{module}.py", f"{module}/__init__.py"]
        if found.group(1):  # `from package import module` names a file too
            names = [n.strip() for n in found.group(2).split(",") if n.strip()]
            candidates = [f"{module}/{n}.py" for n in names] + candidates
        out += [c for c in candidates if c in known and c not in out]
    return out


def quiet_test_files(before: JobResult, tests: Iterable[str]) -> list[str]:
    """Test files with no failing test on the starter: the planted issue they target may be
    missing (a writer sometimes writes the fixed version)."""
    failing = set(re.findall(r"^(?:FAILED|ERROR) (tests/[^:\s]+)", before.stdout, flags=re.M))
    return [t for t in tests if t not in failing]


def failing_tests(output: str) -> list[str]:
    """Test files pytest reports as failing or erroring, in the order it reports them."""
    found = re.findall(r"^(?:FAILED|ERROR) (tests/[^:\s]+\.py)", output, flags=re.M)
    return list(dict.fromkeys(found))


def focus(output: str, files: dict[str, str], round_number: int) -> list[str]:
    """The files one repair round works on: one failing test file (a different one each round,
    so every failing file gets its turn) with the source files its traceback names and the
    modules it imports, sources first. A small model fixes one thing well, not four."""
    code = [p for p in files if p.endswith(".py")]
    named = mentioned(output, code)
    failing = [t for t in failing_tests(output) if t in files] or [
        p for p in named if p.startswith("tests/")
    ]
    if not failing:
        return named or [p for p in code if p.startswith("tests/")]
    test = failing[(round_number - 1) % len(failing)]
    sources = [p for p in named if not p.startswith("tests/")]
    sources += [m for m in imported(files[test], files) if m not in sources]
    sources = [p for p in sources if not p.endswith("__init__.py")] or sources
    return [*sources[:1], test, *sources[1:]]


def starter_verdict(before: JobResult) -> str:
    """'' when the starter's tests run and fail, as planted issues should make them."""
    if before.timed_out:
        return "the starter's tests timed out"
    if before.exit_code == PYTEST_FAILED:
        return ""
    if before.exit_code == 0:
        return "the starter already passes its tests, so nothing is planted"
    output = tail(before.stdout + before.stderr)
    return f"the starter does not run (pytest exit {before.exit_code}): {output}"


def still_a_test(text: str) -> bool:
    return "def test_" in text and "assert" in text


async def build_artifacts(
    gateway: LLMGateway,
    runner: SandboxRunner,
    blueprint: ProjectBlueprint,
    *,
    seed: int = SHARED_SEED,
    tier: ModelTier = "judge",
    feedback: str = "",
    budget_usd: float = 1.0,
    reuse: BuiltArtifacts | None = None,
) -> BuiltArtifacts:
    """Plans, writes, generates and runs everything. Returns every check, pass or fail.

    Every check that fails is first repaired where it failed: the error goes back to the
    writer with the files it names, and the check runs again, up to REPAIRS times. With a
    local model these rounds cost nothing; a whole new attempt costs planning calls.

    With `reuse` (an earlier attempt whose starter passed its checks) the starter is kept and
    only the reference solution is planned and written again, which saves most of the calls."""
    tickets, rubric, issues = listing(blueprint)
    spend = Spend()
    built = BuiltArtifacts(starter={}, reference={}, key={}, metrics={}, summary="")
    keep = f"Keep these planted issues exactly where the plan puts them, unmentioned:\n{issues}"
    repairs = REPAIRS if writer_is_local(gateway, tier, "repair-file") else HOSTED_REPAIRS
    # A later attempt writes warmer: a deterministic local model would write the same files.
    write_temperature = 0.6 if feedback else 0.3

    def finish() -> BuiltArtifacts:
        built.cost_usd, built.model = spend.cost_usd, spend.model
        built.calls = dict(spend.calls)
        return built

    contract = {"notes": ""}  # the starter plan's shared contract, once there is one

    async def fix(
        goal: str, problem: str, files: dict[str, str], editable: list[str], round_number: int = 1
    ) -> dict[str, str]:
        if contract["notes"]:
            goal += f"\n\nThe plan's notes (the contract every file follows):\n{contract['notes']}"
        return await repair_files(
            gateway, spend, tier=tier, budget_usd=budget_usd, scenario=blueprint.scenario,
            goal=goal, problem=problem, files=files, editable=editable, round_number=round_number,
            hard=repairs >= HOSTED_ROUND and round_number == HOSTED_ROUND,
        )  # fmt: skip

    async def valid(files: dict[str, str], paths: Iterable[str], extra: str) -> list[str]:
        """Repairs, in place, each of `paths` that does not compile or parse, or imports a
        package the sandbox does not have. Returns the problems left."""
        paths = list(paths)

        def problem(path: str) -> str | None:
            if why := file_problems({path: files[path]}).get(path):
                return why
            if packages := missing_packages(files).get(path):
                return (
                    f"imports {', '.join(packages)}, which the sandbox does not have (it has only "
                    "the standard library, numpy, pandas, requests and pytest, and no network): "
                    "do the same with those, or take the dependency as an argument that tests "
                    "replace with a fake"
                )
            return None

        for path in [p for p in paths if problem(p)]:
            for number in range(1, repairs + 1):
                why = problem(path)
                if why is None:
                    break
                goal = f"Make {path} a valid file of its type that does what it is for. {extra}"
                changed = await fix(goal, f"{path}: {why}", files, [path], number)
                files.update({p: t for p, t in changed.items() if p == path})
        return [f"{p}: {why}" for p in paths if (why := problem(p))]

    async def make_starter() -> bool:
        system, user = load_prompt(PLAN_STARTER_VERSION)
        notes = feedback
        found: list[str] = []
        for _ in range(REPLANS):
            try:
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
                                feedback=notes or "(none: this is the first attempt)",
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
            except StructuredOutputError as exc:  # a plan that never parsed: plan again
                found = [f"The plan was not valid JSON for the schema: {str(exc)[:300]}"]
                continue
            assert planned.parsed is not None
            spend.add(planned.cost_usd, planned.model)
            plan = repair_plan(planned.parsed)
            found = plan_problems(
                [f.path for f in plan.starter_files],
                [f.path for f in plan.key_files],
                plan.generated,
            )
            if not found:
                break
            # A bad plan costs one cheap call to redo, not the files written from it.
            notes = (feedback + "\n" if feedback else "") + "\n".join(f"- {p}" for p in found)
        else:
            built.checks.append(Check("starter files are well formed", False, " ".join(found)))
            return False
        every = [*plan.starter_files, *with_key_contracts(plan.key_files, plan.generated)]
        contract["notes"] = built.design_notes = plan.design_notes

        def render_starter(group: list[PlannedFile], written: dict[str, str]) -> dict[str, str]:
            return {
                "scenario": blueprint.scenario,
                "notes": plan.design_notes,
                "plan": plan_text(every),
                "written": shown_outline(written),
                "targets": targets_text(group),
            }

        local = writer_is_local(gateway, tier, "write-starter-file")
        try:
            files = await write_files(
                gateway, spend, purpose="write-starter-file", tier=tier,
                version=WRITE_ONE_FILE_VERSION if local else WRITE_FILE_VERSION,
                planned=every, render=render_starter, budget_usd=budget_usd,
                temperature=write_temperature, **local_writing(local),
            )  # fmt: skip
            for item in plan.starter_files:  # what the person receives gives nothing away
                files[item.path] = without_hints(item.path, files[item.path])
            broken = await valid(files, [i.path for i in every], keep)
            draft = StarterDraft(
                starter_files=[
                    FileDraft(path=i.path, content=files[i.path]) for i in plan.starter_files
                ],
                key_files=[FileDraft(path=i.path, content=files[i.path]) for i in plan.key_files],
                generated=plan.generated,
            )
        except (FileWriteError, ValidationError) as exc:
            built.checks.append(Check("starter files are written", False, str(exc)[:600]))
            return False
        if problems := [*starter_problems(draft), *broken]:
            built.checks.append(Check("starter files are well formed", False, " ".join(problems)))
            return False
        built.checks.append(Check("starter files are well formed", True))

        starter = {f.path: f.content for f in draft.starter_files}
        key = {f.path: f.content for f in draft.key_files}

        def apply(changed: dict[str, str]) -> None:
            for path, text in changed.items():
                if is_key_path(path):
                    key[path] = text
                else:
                    starter[path] = without_hints(path, text)

        generator_goal = (
            f"`python -m key.make_data --seed {seed}`, run from the repository root, must exit 0 "
            f"and write exactly these files: {', '.join(draft.generated)}. It takes --seed N, "
            "writes the same files for the same seed, creates every folder it writes into, and "
            f"runs in seconds. {keep}"
        )
        made_problem = verdict = ""
        generator_rounds = test_rounds = 0
        while True:
            made = await runner.run(
                SandboxJob(
                    files={**output_dirs(draft.generated), **tree(starter, key)},
                    command=["python", "-m", "key.make_data", "--seed", str(seed)],
                    collect=draft.generated,
                    timeout_s=60,
                )
            )
            missing = [p for p in draft.generated if p not in made.files]
            made_problem = (
                ""
                if made.ok and not missing
                else f"exit {made.exit_code}; missing {missing}; "
                f"{tail(made.stdout + made.stderr, 25)}"
            )
            if made.ok and missing:
                made_problem += (
                    "\nIt ran without an error but did not write those files: when run as "
                    "`python -m key.make_data --seed N`, module-level code must parse --seed and "
                    "call the code that writes every one of them, at exactly those paths."
                )
            if made_problem:
                if generator_rounds == repairs:
                    break
                generator_rounds += 1
                code = tree(starter, key)
                sources = [p for p in code if p.endswith(".py") and not p.startswith("tests/")]
                named = [p for p in mentioned(made_problem, sources) if p != GENERATOR]
                apply(
                    await fix(
                        generator_goal, made_problem, code, [GENERATOR, *named], generator_rounds
                    )
                )
                continue
            with_data = tree(starter, {p: t for p, t in made.files.items() if not is_key_path(p)})
            before = await runner.run(
                SandboxJob(files=with_data, command=TEST_COMMAND, timeout_s=120)
            )
            verdict = starter_verdict(before)
            if not verdict or test_rounds == repairs:
                break
            test_rounds += 1
            output = before.stdout + before.stderr
            tests = [p for p in starter if p.startswith("tests/") and p.endswith(".py")]
            if before.exit_code == 0:
                goal = (
                    "The target tests pass on this starter, so they do not catch the planted "
                    "issues. Make sure each planted issue is really in the code or data, written "
                    "as ordinary code with no comment about it, and that the tests in tests/ "
                    "check the acceptance criteria of the code tickets, so that they fail on "
                    "this code because of the planted issues and pass once the issues are fixed "
                    "properly. Plain asserts, no randomness.\n"
                    f"Planted issues:\n{issues}\nTickets:\n{tickets}"
                )
                editable = [t for test in tests for t in (test, *imported(starter[test], starter))]
            else:
                goal = (
                    "The target tests in tests/ must be collected and run without errors (no "
                    "import, syntax or fixture errors, no hang) and fail only because of the "
                    f"planted issues. Fix what the output shows. {keep}"
                )
                editable = focus(output, starter, test_rounds)
            apply(
                await fix(goal, f"{verdict}\n{tail(output, 40)}", with_data, editable, test_rounds)
            )

        built.checks.append(
            Check("the data generator runs and writes every file it lists", not made_problem,
                  made_problem)
        )  # fmt: skip
        built.starter, built.key = dict(starter), dict(key)
        if made_problem:
            return False
        for path, text in made.files.items():
            (built.key if is_key_path(path) else built.starter)[path] = text
        built.checks.append(
            Check("the starter runs and fails its target tests", not verdict, verdict)
        )
        if not verdict:
            tests = [p for p in starter if p.startswith("tests/test_") and p.endswith(".py")]
            built.notes += [
                f"{t} passes on the starter: check that the planted issue it targets is there."
                for t in quiet_test_files(before, tests)
            ]
        return True

    if reuse is not None and reuse.starter_ok:
        built.starter, built.key = dict(reuse.starter), dict(reuse.key)
        built.checks += [c for c in reuse.checks if c.name in STARTER_CHECKS]
        contract["notes"] = built.design_notes = reuse.design_notes
    elif not await make_starter():
        return finish()
    starter = built.starter

    system, user = load_prompt(PLAN_REFERENCE_VERSION)
    try:
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
                        starter=shown_preview(starter),
                        feedback=feedback or "(none: this is the first attempt)",
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
    except StructuredOutputError as exc:
        built.checks.append(Check("reference plan is well formed", False, str(exc)[:600]))
        return finish()
    assert ref_planned.parsed is not None
    ref_plan = ref_planned.parsed
    spend.add(ref_planned.cost_usd, ref_planned.model)
    built.summary = ref_plan.summary
    if problems := reference_problems(ref_plan, starter):
        built.checks.append(Check("reference plan is well formed", False, " ".join(problems)))
        return finish()

    def render_reference(group: list[PlannedFile], written: dict[str, str]) -> dict[str, str]:
        targets = {i.path for i in group}
        return {
            "scenario": blueprint.scenario,
            "plan": plan_text(ref_plan.changes),
            # the files being changed in full; the rest as outlines, to keep the prompt small
            "starter": "\n\n".join(
                f"=== {p} ===\n{t if p in targets else outline(p, t)}"
                for p, t in sorted(starter.items())
            ),
            "written": shown(written),
            "targets": targets_text(group),
        }

    local = writer_is_local(gateway, tier, "write-reference-file")
    try:
        changed = await write_files(
            gateway, spend, purpose="write-reference-file", tier=tier,
            version=WRITE_ONE_REFERENCE_VERSION if local else WRITE_REFERENCE_VERSION,
            planned=ref_plan.changes, render=render_reference, budget_usd=budget_usd,
            temperature=write_temperature, **local_writing(local),
        )  # fmt: skip
    except FileWriteError as exc:
        built.checks.append(Check("reference files are written", False, str(exc)))
        return finish()
    whole = tree(starter, changed)
    broken = await valid(whole, list(changed), "")
    changed = {p: whole[p] for p in changed}
    built.checks.append(Check("reference files are written", not broken, " ".join(broken)))
    if broken:
        return finish()

    rounds = 0
    while True:
        reference = tree(starter, changed)
        after = await runner.run(
            SandboxJob(files=dict(reference), command=TEST_COMMAND, timeout_s=120)
        )
        if after.ok or rounds == repairs:
            break
        rounds += 1
        output = after.stdout + after.stderr
        code = {p: t for p, t in reference.items() if not is_key_path(p)}
        goal = (
            "Every test must pass on the fixed project. Fix the planted issues properly in the "
            f"source code:\n{issues}\nChange a test only if the test itself is wrong (for "
            "example an expected value worked out wrongly), never to weaken what it checks, and "
            "never delete a test. The plan's notes below are the specification: where a test "
            "disagrees with them, the test is wrong; where the code does, the code is."
        )
        fixed = await fix(goal, output, reference, focus(output, code, rounds), rounds)
        # A starter test the repair corrected; the reference's own new tests stay its own.
        new_tests = {
            p: without_hints(p, t)
            for p, t in fixed.items()
            if p.startswith("tests/") and p in starter
        }
        if new_tests and all(still_a_test(t) for t in new_tests.values()):
            # A corrected test must still fail on the starter, or it no longer finds anything.
            check = await runner.run(
                SandboxJob(files=tree(starter, new_tests), command=TEST_COMMAND, timeout_s=120)
            )
            if check.exit_code == PYTEST_FAILED and not check.timed_out:
                starter = tree(starter, new_tests)
                built.starter = starter
        changed.update({p: t for p, t in fixed.items() if p not in new_tests})
    built.reference = reference
    built.checks.append(
        Check(
            "the reference solution passes every test",
            after.ok,
            "" if after.ok else f"exit {after.exit_code}: {tail(after.stdout + after.stderr)}",
        )
    )
    if not after.ok:
        return finish()

    metrics_goal = (
        "`python -m key.metrics`, run from the repository root of the fixed project with the key "
        "files present, must exit 0 and write metrics.json: one flat JSON object of numbers (no "
        "nesting, strings or booleans) covering the numbers the rubric checks and the planted "
        "issues refer to."
    )
    rounds = 0
    while True:
        measured = await runner.run(
            SandboxJob(
                files=tree(reference, built.key),
                command=["python", "-m", "key.metrics"],
                collect=["metrics.json"],
                timeout_s=60,
            )
        )
        written_metrics = measured.files.get("metrics.json", "")
        metrics = parse_metrics(written_metrics)
        metrics_ok = measured.ok and bool(metrics)
        if metrics_ok or rounds == repairs:
            break
        rounds += 1
        problem = (
            f"exit {measured.exit_code}; metrics.json: {written_metrics[:400] or '(not written)'}"
            f"\n{tail(measured.stdout + measured.stderr, 30)}"
        )
        changed_key = await fix(
            metrics_goal, problem, tree(reference, built.key), [METRICS_SCRIPT], rounds
        )
        built.key.update({p: t for p, t in changed_key.items() if is_key_path(p)})
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
    if built.notes:
        lines += ["", "## For the reviewer", *[f"- {n}" for n in built.notes]]
    if built.summary:
        lines += ["", "## What the reference changes", built.summary]
    calls = ", ".join(f"{m} {n}" for m, n in sorted(built.calls.items(), key=lambda c: -c[1]))
    lines += ["", f"_Model calls: {calls or 'none'}. Cost: ${built.cost_usd:.2f}._"]
    if folder is not None:
        lines.append(f"Files: {folder}")
    return "\n".join(lines)
