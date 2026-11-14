"""Portfolio output: every number is measured, nothing about the answer key leaves."""

import io
import uuid
import zipfile

from firstweek_core.contracts import SupervisorVerdict
from firstweek_core.sandbox import JobResult
from firstweek_simulation import portfolio
from firstweek_simulation.workspace import Project

PROJECT = Project(
    uuid.uuid4(),
    {
        "archetype": "GenAI Engineer",
        "scenario": "The dashboard says 90% accuracy. Is it true?",
        "rubric": [
            {"skill_id": "python", "weight": 0.6},
            {"skill_id": "testing", "weight": 0.4},
        ],
    },
    {
        "src/calc.py": "def total(xs):\n    return 0\n",
        "tests/test_calc.py": "def test_a():\n    pass\n",
    },
)
VERDICT = SupervisorVerdict(
    summary="A solid first week with one metric fixed and one gap left open.",
    skills=[
        {"skill_id": "testing", "score": 3, "evidence": "One new test was added."},
        {"skill_id": "python", "score": 5, "evidence": "Small, correct change to total."},
    ],
    went_well=["Fixed the total"],
    to_work_on=["More tests"],
    next_step="Write a test that fails on the old total.",
)
EDITS = {
    "src/calc.py": "def total(xs):\n    return sum(xs)\n",
    "tests/test_mine.py": "def test_b():\n    assert 1\n",
}


def ran(code: int, out: str) -> JobResult:
    return JobResult(exit_code=code, stdout=out, stderr="", timed_out=False, duration_s=1)


def test_measures_come_from_the_run_and_the_files() -> None:
    m = portfolio.measure(PROJECT, EDITS, ran(0, "2 passed in 0.1s"))
    assert (m.tests_passed, m.tests_failed, m.run_ok) == (2, 0, True)
    assert m.changed_files == 2 and m.new_tests == 1


def test_matrix_is_strongest_first_with_a_weighted_score() -> None:
    rows = portfolio.skill_matrix(PROJECT, VERDICT)
    assert [r.skill_id for r in rows] == ["python", "testing"]
    assert portfolio.weighted_score(rows) == 4.2  # (5*0.6 + 3*0.4) / 1.0


def test_bullets_use_only_measured_numbers_and_skip_weak_skills() -> None:
    m = portfolio.measure(PROJECT, EDITS, ran(0, "2 passed"))
    rows = portfolio.skill_matrix(PROJECT, VERDICT)
    text = " ".join(portfolio.cv_bullets("GenAI Engineer", PROJECT, rows, m, reviewer="X"))
    assert "all 2 automated tests" in text and "1 I wrote" in text
    assert "python" in text and "testing" not in text
    assert "practice simulation, not employment" in text


def test_a_failing_run_is_reported_as_failing() -> None:
    m = portfolio.measure(PROJECT, {}, ran(1, "1 failed, 1 passed"))
    bullets = portfolio.cv_bullets("GenAI Engineer", PROJECT, [], m, reviewer="X")
    assert any("1 failing" in b for b in bullets)


def test_the_zip_holds_the_repo_but_never_the_hidden_side() -> None:
    edits = {**EDITS}
    project = Project(
        PROJECT.blueprint_id, PROJECT.blueprint, {**PROJECT.files, "key/secret.py": "x"}
    )
    summary, data = portfolio.build_export(
        "GenAI Engineer", project, edits, ran(0, "2 passed"), VERDICT, reviewer="X"
    )
    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    assert "repo/src/calc.py" in names and "CV_BULLETS.md" in names
    assert not any(n.startswith("repo/key/") for n in names)
    assert summary["weighted_score"] == 4.2
