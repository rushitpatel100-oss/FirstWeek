"""A hand-written practice project, ready without any model call (ADR 0022).

Autopilot writes projects with a model and gates them; this one is written by a person and kept
in code so the workspace can be tried, demoed and tested the moment a role has a report. It is
labelled as hand-written everywhere it is shown to the owner; it is not model output and makes
no claim about any real company. The project: an insurer's claims assistant reports about 90%
citation accuracy, support says that is wrong. Two realistic bugs inflate the number; the
learner finds and fixes them, then writes a regression test."""

import json
import random
import uuid
from pathlib import Path

from sqlalchemy import select

from firstweek_core.contracts import AnswerKey, Criterion, ProjectBlueprint, Ticket
from firstweek_core.db.models import ArchetypeVersion, Blueprint, RoleArchetype
from firstweek_core.db.session import session_scope
from firstweek_simulation.blueprint import BlueprintError
from firstweek_simulation.demo_internship import internship
from firstweek_simulation.internship import write_internship

ROWS = 120
CLAUSES = 40
SEED = 7

LOAD_BUGGY = '''import json
from pathlib import Path


def load_rows(path):
    """Rows of the evaluation set, ready for scoring."""
    rows = json.loads(Path(path).read_text())
    return [row for row in rows if row["cited_clause"]]
'''
LOAD_FIXED = '''import json
from pathlib import Path


def load_rows(path):
    """Rows of the evaluation set, ready for scoring."""
    return json.loads(Path(path).read_text())
'''
METRIC_BUGGY = '''def citation_accuracy(rows):
    """Share of answers whose cited clause is the clause the answer should rest on."""
    if not rows:
        return 0.0
    correct = sum(1 for row in rows if row["cited_clause"] in row["expected_clause"])
    return correct / len(rows)
'''
METRIC_FIXED = '''def citation_accuracy(rows):
    """Share of answers whose cited clause is the clause the answer should rest on."""
    if not rows:
        return 0.0
    correct = sum(1 for row in rows if row["cited_clause"] == row["expected_clause"])
    return correct / len(rows)
'''
REPORT = '''from src.evalset import load_rows
from src.metrics import citation_accuracy


def summary(path="data/eval_set.json"):
    """The numbers the weekly dashboard shows."""
    rows = load_rows(path)
    return {"rows": len(rows), "citation_accuracy": round(citation_accuracy(rows), 3)}


if __name__ == "__main__":
    print(summary())
'''
README = """# Claims assistant: evaluation

`data/eval_set.json` holds one row per test question: the clause the answer should rest on
(`expected_clause`) and the clause the assistant actually cited (`cited_clause`, empty when it
cited nothing). `python -m src.report` prints the numbers on the weekly dashboard.

Run the tests with `python -m pytest`.
"""
TESTS = """import json

from src.evalset import load_rows
from src.metrics import citation_accuracy
from src.report import summary


def row(expected, cited):
    return {"id": 1, "expected_clause": expected, "cited_clause": cited}


def test_an_empty_set_scores_zero():
    assert citation_accuracy([]) == 0.0


def test_a_clause_that_is_only_the_start_of_the_right_one_is_not_a_match():
    assert citation_accuracy([row("C-23", "C-2")]) == 0.0


def test_an_answer_with_no_citation_counts_as_wrong(tmp_path):
    path = tmp_path / "set.json"
    path.write_text(json.dumps([row("C-5", "C-5"), row("C-6", "")]))
    assert citation_accuracy(load_rows(path)) == 0.5


def test_the_dashboard_matches_a_hand_count_on_the_real_set():
    rows = json.load(open("data/eval_set.json"))
    right = sum(1 for r in rows if r["cited_clause"] == r["expected_clause"])
    assert summary()["rows"] == len(rows)
    assert summary()["citation_accuracy"] == round(right / len(rows), 3)
"""
SCENARIO = (
    "Northwind Claims, a mid-sized insurer, runs an AI assistant that answers customers' policy "
    "questions and cites the policy clause behind each answer. The weekly dashboard says the "
    "assistant cites the right clause about 90% of the time, but the support team keeps finding "
    "answers that point at the wrong clause. Your first week is about finding out which one is "
    "telling the truth."
)
CONTEXT = (
    "Northwind has about 60 staff and a three-person AI team. The assistant is used by the "
    "support team and, soon, by customers directly, so a wrong citation can mean a wrong "
    "decision on a claim."
)


def eval_rows() -> list[dict[str, object]]:
    """The evaluation set: mostly right, some wrong, some uncited, some near-miss ids."""
    rng = random.Random(SEED)
    rows: list[dict[str, object]] = []
    for i in range(1, ROWS + 1):
        expected_n = rng.randint(10, CLAUSES)  # two digits, so "C-2" is a prefix of "C-23"
        expected = f"C-{expected_n}"
        roll = rng.random()
        if roll < 0.55:
            cited = expected
        elif roll < 0.80:
            cited = f"C-{str(expected_n)[0]}"  # the first digit only: a prefix of the right one
        elif roll < 0.90:
            cited = f"C-{rng.choice([n for n in range(10, CLAUSES + 1) if n != expected_n])}"
        else:
            cited = ""
        rows.append({"id": i, "expected_clause": expected, "cited_clause": cited})
    return rows


def truth(rows: list[dict[str, object]]) -> float:
    return sum(1 for r in rows if r["cited_clause"] == r["expected_clause"]) / len(rows)


def starter_reading(rows: list[dict[str, object]]) -> float:
    """What the buggy dashboard reports on the same rows."""
    kept = [r for r in rows if r["cited_clause"]]
    hits = sum(1 for r in kept if str(r["cited_clause"]) in str(r["expected_clause"]))
    return hits / len(kept)


def files() -> tuple[dict[str, str], dict[str, str]]:
    """(starter, reference) file contents."""
    data = json.dumps(eval_rows(), indent=0)
    shared = {"README.md": README, "src/__init__.py": "", "src/report.py": REPORT,
              "tests/test_metrics.py": TESTS, "data/eval_set.json": data}  # fmt: skip
    starter = {**shared, "src/evalset.py": LOAD_BUGGY, "src/metrics.py": METRIC_BUGGY}
    reference = {**shared, "src/evalset.py": LOAD_FIXED, "src/metrics.py": METRIC_FIXED}
    return starter, reference


def tickets() -> list[Ticket]:
    return [
        Ticket(
            key="NW-101",
            title="The dashboard says 90% citation accuracy. Is it true?",
            description=(
                "Support keeps finding wrong citations, yet the dashboard reports about 90%. "
                "Work out how the number is computed, find why it is too high and fix the "
                "metric so it matches a hand count on the whole evaluation set."
            ),
            acceptance_criteria=[
                "A clause that is only the start of the right one (C-2 for C-23) is not a match",
                "The dashboard number equals a hand count on data/eval_set.json",
            ],
            task_type="code",
            due_day=1,
            skills=["llm-evaluation", "python"],
        ),
        Ticket(
            key="NW-102",
            title="Answers with no citation must count against us",
            description=(
                "When the assistant cites nothing, that is a failure to ground the answer, but "
                "the evaluation loader quietly drops those rows. Make them count as wrong."
            ),
            acceptance_criteria=[
                "Rows with no citation stay in the evaluation and count as wrong",
                "The given test for uncited answers passes",
            ],
            task_type="code",
            due_day=2,
            skills=["llm-evaluation", "hallucination-mitigation"],
        ),
        Ticket(
            key="NW-103",
            title="Make sure this cannot quietly come back",
            description=(
                "Add a regression test of your own in a new file under tests/ that fails on the "
                "original code and passes on your fix, and keep your changes small enough for "
                "someone else to review quickly."
            ),
            acceptance_criteria=[
                "A new test fails on the original code and passes on the fix",
                "Existing tests still pass",
            ],
            task_type="code",
            due_day=3,
            skills=["testing", "python"],
        ),
    ]


def _anchors(low: str, mid: str, high: str) -> list[str]:
    return [low, "Partly there, with gaps.", mid, "Solid, with one small gap.", high]


def rubric() -> list[Criterion]:
    def crit(skill: str, weight: float, anchors: list[str], checks: list[str]) -> Criterion:
        return Criterion(
            skill_id=skill, weight=weight, anchors=dict(enumerate(anchors, 1)), checks=checks
        )

    return [
        crit("llm-evaluation", 0.35,
             _anchors("Trusts the dashboard number without checking.",
                      "Finds one of the two causes and explains it.",
                      "Finds both causes, explains each and checks the number by hand."),
             ["tests/test_metrics.py passes", "dashboard equals the hand count"]),
        crit("python", 0.20,
             _anchors("Edits that break other code.", "Correct but clumsy fixes.",
                      "Small, clear, correct changes."),
             ["no test regressions"]),
        crit("hallucination-mitigation", 0.20,
             _anchors("Treats uncited answers as fine.", "Counts them, with no reasoning.",
                      "Explains why an uncited answer is an ungrounded one."),
             ["uncited rows counted as wrong"]),
        crit("testing", 0.25,
             _anchors("No new test.", "A test that passes before and after the fix.",
                      "A focused test that fails on the old code and passes on the fix."),
             ["new test fails on the starter", "new test passes on the reference"]),
    ]  # fmt: skip


PLANTED = [
    "metrics.citation_accuracy uses `in` on strings, so C-2 matches C-23 (a prefix is not a match)",
    "evalset.load_rows drops rows with no citation, so uncited answers never count as wrong",
]


def blueprint(role_name: str, folder: Path) -> ProjectBlueprint:
    rows = eval_rows()
    return ProjectBlueprint(
        archetype=role_name, scenario=SCENARIO, company_context=CONTEXT,
        tickets=tickets(), rubric=rubric(),
        answer_key=AnswerKey(
            reference_solution_uri=(folder / "reference").resolve().as_uri(),
            planted_issues=PLANTED,
            expected_metrics={
                "citation_accuracy": round(truth(rows), 3),
                "dashboard_claims": round(starter_reading(rows), 3),
            },
        ),
    )  # fmt: skip


def seed_demo(slug: str, root: Path) -> uuid.UUID:
    """Stores the project as an approved blueprint for the role and writes its files."""
    with session_scope() as session:
        found = session.execute(
            select(ArchetypeVersion.id, RoleArchetype.name)
            .join(RoleArchetype, RoleArchetype.id == ArchetypeVersion.archetype_id)
            .where(RoleArchetype.slug == slug)
            .order_by(ArchetypeVersion.created_at.desc())
            .limit(1)
        ).first()
        if found is None:
            raise BlueprintError(f'No report data for "{slug}". Run `make report` first.')
        version_id, role_name = found
        new_id = uuid.uuid4()
        project = blueprint(role_name, root / str(new_id))
        session.add(Blueprint(
            id=new_id, archetype_version_id=version_id, scenario=project.scenario,
            blueprint=project.public_view(), answer_key=project.answer_key.model_dump(),
            validated=True, status="approved",
        ))  # fmt: skip
    _write_files(root / str(new_id))
    write_internship(root, new_id, internship())
    return new_id


def _write_files(folder: Path) -> None:
    starter, reference = files()
    for name, content in (("starter", starter), ("reference", reference)):
        for path, text in content.items():
            target = folder / name / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)


def ensure_demo(slug: str, root: Path) -> tuple[uuid.UUID, str]:
    """Idempotent seeding for a deployed API: run on every start, change nothing that is fine.

    Returns (blueprint id, what happened): "kept", "files restored" (the database has the demo
    but this container's disk lost its files) or "seeded"."""
    with session_scope() as session:
        found = session.execute(
            select(Blueprint.id)
            .join(ArchetypeVersion, Blueprint.archetype_version_id == ArchetypeVersion.id)
            .join(RoleArchetype, ArchetypeVersion.archetype_id == RoleArchetype.id)
            .where(
                RoleArchetype.slug == slug,
                Blueprint.status == "approved",
                Blueprint.scenario == SCENARIO,
            )
            .order_by(Blueprint.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
    if found is None:
        return seed_demo(slug, root), "seeded"
    folder = root / str(found)
    if (folder / "starter").is_dir() and (folder / "internship.json").is_file():
        return found, "kept"
    _write_files(folder)
    write_internship(root, found, internship())
    return found, "files restored"
