"""The hand-written demo project must itself pass the gate autopilot applies to model output."""

from pathlib import Path

import pytest
from sqlalchemy import delete, text
from sqlalchemy.exc import OperationalError
from test_artifacts import LocalRunner

from firstweek_core.db.models import ArchetypeVersion, Blueprint, RoleArchetype
from firstweek_core.db.session import get_engine, session_scope
from firstweek_core.sandbox import SandboxJob
from firstweek_simulation import demo_project as demo
from firstweek_simulation.blueprint import BlueprintError

TEST_COMMAND = ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]


async def run(files: dict[str, str]) -> int:
    result = await LocalRunner().run(SandboxJob(files=files, command=TEST_COMMAND))
    return result.exit_code


async def test_the_starter_fails_its_tests_and_the_reference_passes_them() -> None:
    starter, reference = demo.files()
    assert await run(starter) == 1
    assert await run(reference) == 0


async def test_each_planted_bug_is_caught_by_its_own_test() -> None:
    starter, reference = demo.files()
    only_metric = {**reference, "src/metrics.py": starter["src/metrics.py"]}
    only_loader = {**reference, "src/evalset.py": starter["src/evalset.py"]}
    assert await run(only_metric) == 1
    assert await run(only_loader) == 1


def test_the_buggy_dashboard_overstates_what_the_hand_count_says() -> None:
    rows = demo.eval_rows()
    assert demo.starter_reading(rows) >= 0.88  # the roughly 90% the story says
    assert demo.truth(rows) < 0.65
    assert demo.eval_rows() == demo.eval_rows()  # deterministic


def test_the_blueprint_is_valid_and_the_public_view_hides_the_key(tmp_path: Path) -> None:
    project = demo.blueprint("GenAI Engineer", tmp_path)
    public = str(project.public_view())
    assert "planted_issues" not in public and "reference_solution_uri" not in public
    assert not any(issue in public for issue in demo.PLANTED)


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
        session.execute(delete(RoleArchetype))


@pytest.mark.db
@pytest.mark.usefixtures("_db")
def test_seeding_stores_an_approved_project_the_workspace_can_open(tmp_path: Path) -> None:
    from datetime import date

    from firstweek_simulation.workspace import approved_project

    with pytest.raises(BlueprintError, match="make report"):
        demo.seed_demo("genai-engineer", tmp_path)
    with session_scope() as session:
        role = RoleArchetype(
            slug="genai-engineer", name="GenAI Engineer", definition="d", trust_level="golden"
        )
        session.add(role)
        session.flush()
        session.add(ArchetypeVersion(
            archetype_id=role.id, version=1, country="GB", date_from=date(2026, 5, 1),
            date_to=date(2026, 10, 1), sample_size=15, status="published",
        ))  # fmt: skip
    new_id = demo.seed_demo("genai-engineer", tmp_path)
    found = approved_project("genai-engineer", tmp_path)
    assert found is not None and found.blueprint_id == new_id
    assert "src/metrics.py" in found.files and "tests/test_metrics.py" in found.files
    assert not any(p.startswith(("key/", "reference/")) for p in found.files)
    assert "reference" not in str(found.blueprint).lower() or "planted" not in str(found.blueprint)
