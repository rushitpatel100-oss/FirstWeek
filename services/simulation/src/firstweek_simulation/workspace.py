"""The practice workspace behind the API: load a project, run the learner's tests, ask the
Tech Lead (ADR 0021).

Learners only ever receive the starter side and the public blueprint. The answer key, the
reference solution and the hidden `key/` scripts stay on disk and in the database, and the
Tech Lead is built from the public view too, so it cannot leak what it does not have."""

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select

from firstweek_core.db.models import ArchetypeVersion, Blueprint, RoleArchetype
from firstweek_core.db.session import session_scope
from firstweek_core.llm import LLMGateway
from firstweek_core.llm import Tier as ModelTier
from firstweek_core.sandbox import JobResult, SandboxJob, SandboxRunner
from firstweek_simulation.blueprint import load_prompt

TEST_COMMAND = ["python", "-m", "pytest", "-q", "--tb=short", "-p", "no:cacheprovider"]
TEST_TIMEOUT_S = 60.0
REVIEW_VERSION = "tech-lead-review.v1"
REVIEW_FILE_CHARS = 24_000  # what the reviewer reads, so a big paste cannot run up the bill
REVIEW_TEST_CHARS = 4_000


class WorkspaceError(Exception):
    """Something the learner can fix: an unknown ticket, a file that is not allowed."""


@dataclass(frozen=True)
class Project:
    blueprint_id: uuid.UUID
    blueprint: dict[str, Any]  # the public view: no answer key
    files: dict[str, str]  # the starter side only


def approved_project(slug: str, root: Path) -> Project | None:
    """The newest approved project for a role, or None if there is none (or no files)."""
    with session_scope() as session:
        row = session.execute(
            select(Blueprint)
            .join(ArchetypeVersion, Blueprint.archetype_version_id == ArchetypeVersion.id)
            .join(RoleArchetype, ArchetypeVersion.archetype_id == RoleArchetype.id)
            .where(RoleArchetype.slug == slug, Blueprint.status == "approved")
            .order_by(Blueprint.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if row is None:
            return None
        blueprint_id, blueprint = row.id, dict(row.blueprint)
    starter = root / str(blueprint_id) / "starter"
    if not starter.is_dir():
        return None
    files = {
        path.relative_to(starter).as_posix(): path.read_text("utf-8")
        for path in sorted(starter.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }
    return Project(blueprint_id, blueprint, files)


def with_edits(project: Project, edits: dict[str, str]) -> dict[str, str]:
    """The starter plus the learner's changes. The given tests cannot be rewritten (new test
    files can be added), and nothing may reach the hidden side."""
    merged = dict(project.files)
    for path, text in edits.items():
        if path.split("/")[0] == "key":
            raise WorkspaceError(f"{path} is not part of your project.")
        if path in project.files and path.startswith("tests/"):
            continue
        merged[path] = text
    return merged


async def run_tests(runner: SandboxRunner, project: Project, edits: dict[str, str]) -> JobResult:
    job = SandboxJob(
        files=with_edits(project, edits), command=TEST_COMMAND, timeout_s=TEST_TIMEOUT_S
    )
    return await runner.run(job)


def ticket_of(project: Project, key: str) -> dict[str, Any]:
    for ticket in project.blueprint["tickets"]:
        if ticket["key"] == key:
            return dict(ticket)
    raise WorkspaceError(f"There is no ticket {key} in this project.")


async def review(
    gateway: LLMGateway,
    project: Project,
    ticket_key: str,
    edits: dict[str, str],
    tests: JobResult | None,
    *,
    tier: ModelTier = "judge",
    budget_usd: float = 0.05,
) -> tuple[str, str]:
    """The Tech Lead's review of the learner's current files. Returns (text, model)."""
    ticket = ticket_of(project, ticket_key)
    files = with_edits(project, edits)
    shown = "\n\n".join(f"--- {p} ---\n{t}" for p, t in files.items() if p.split("/")[0] != "data")
    if tests is None:
        output, code = "(the learner has not run the tests)", "n/a"
    else:
        output, code = (tests.stdout + tests.stderr)[-REVIEW_TEST_CHARS:], str(tests.exit_code)
    system, template = load_prompt(REVIEW_VERSION)
    user = template.format(
        scenario=project.blueprint["scenario"],
        key=ticket["key"],
        title=ticket["title"],
        description=ticket["description"],
        criteria="\n".join(f"- {c}" for c in ticket["acceptance_criteria"]),
        exit_code=code,
        tests=output,
        files=shown[:REVIEW_FILE_CHARS],
    )
    result = await gateway.complete(
        purpose="tech-lead-review",
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        tier=tier,
        budget_scope=f"review:{project.blueprint_id}",
        budget_usd=budget_usd,
        max_tokens=4000,
        prompt_version=REVIEW_VERSION,
    )
    return result.content.strip(), result.model
