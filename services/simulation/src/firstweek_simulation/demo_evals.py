"""A hand-written practice project for the AI Evaluation Engineer role (ADR 0031).

Needs no model call and no library beyond the standard one. The project: the evaluation harness
for a support assistant at a fictional insurer. The dashboard says the assistant answers 88% of
test questions correctly. Two realistic mistakes explain it: the grader gives a pass whenever the
expected phrase appears anywhere in the answer (even in "that is not 30 days"), and the dashboard
leaves out the questions where the assistant timed out, so failures cannot lower the score."""

import json
import random
from typing import Any

from firstweek_core.contracts import Criterion, Internship, Ticket
from firstweek_simulation import demo_kit as kit

SEED = 11
CASES = 60
ERRORS = 8
NEGATED = 8
PLAIN_WRONG = 6

TERMS = [
    "30 days", "14 days", "24 hours", "50 pounds", "two years",
    "5 working days", "12 months", "250 pounds", "48 hours", "10 days",
]  # fmt: skip

GRADE_BUGGY = '''"""Decides whether an answer contains the fact the question was testing."""


def passes(answer, expected):
    return expected in answer
'''
GRADE_FIXED = '''"""Decides whether an answer contains the fact the question was testing."""


def passes(answer, expected):
    text = answer.lower()
    want = expected.lower()
    at = text.find(want)
    if at < 0:
        return False
    before = text[:at].rstrip()
    return not (before == "not" or before.endswith(" not") or before.endswith("n't"))
'''
REPORT_BUGGY = '''"""What the evaluation dashboard shows."""

import json

from src.grade import passes


def summary(path="data/cases.json"):
    cases = json.load(open(path))
    graded = [c for c in cases if c["error"] is None]
    passed = sum(passes(c["answer"], c["expected"]) for c in graded)
    return {
        "pass_rate": round(passed / len(graded), 3),
        "errors": len(cases) - len(graded),
    }


if __name__ == "__main__":
    print(summary())
'''
REPORT_FIXED = '''"""What the evaluation dashboard shows."""

import json

from src.grade import passes


def summary(path="data/cases.json"):
    cases = json.load(open(path))
    passed = sum(
        c["error"] is None and passes(c["answer"], c["expected"]) for c in cases
    )
    return {
        "pass_rate": round(passed / len(cases), 3),
        "errors": sum(c["error"] is not None for c in cases),
    }


if __name__ == "__main__":
    print(summary())
'''
README = """# Support assistant evaluation

`data/cases.json` holds the assistant's answers to a fixed set of test questions. Each case has
the `expected` fact the answer must contain, the `answer` the assistant gave (empty when it failed
to answer) and an `error` (`null` when it answered). `src/grade.py` decides whether one answer
passes; `src/report.py` turns the whole file into the numbers on the evaluation dashboard.

Run the tests with `python -m pytest`.
"""
TESTS = """import json

from src.grade import passes
from src.report import summary


def test_an_answer_that_denies_the_fact_does_not_pass():
    assert passes("You have 30 days to return it.", "30 days")
    assert passes("You have 30 Days to return it.", "30 days")
    assert not passes("That is not 30 days, it is shorter.", "30 days")
    assert not passes("It isn't 24 hours.", "24 hours")
    assert not passes("Please contact support.", "30 days")


def test_questions_the_assistant_failed_to_answer_count_as_failures(tmp_path):
    cases = [
        {"expected": "30 days", "answer": "Yes, 30 days.", "error": None},
        {"expected": "30 days", "answer": "Not 30 days.", "error": None},
        {"expected": "30 days", "answer": None, "error": "timeout"},
        {"expected": "30 days", "answer": "Call us.", "error": None},
    ]
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(cases))
    result = summary(str(path))
    assert result["pass_rate"] == 0.25
    assert result["errors"] == 1
"""
SCENARIO = (
    "Halden Insurance is about to widen its support assistant to all customers. The evaluation "
    "dashboard says the assistant answers 88% of the test questions correctly, and the launch "
    "review is on Friday. Your first week is about finding out how much that number can be "
    "trusted."
)
CONTEXT = (
    "Halden is a mid-sized insurer with about 900 staff. The AI team of nine runs the support "
    "assistant, and an evaluation score is what the launch review looks at, so a number that "
    "flatters the assistant means customers meet its mistakes first."
)


def _cases() -> list[dict[str, Any]]:
    rng = random.Random(SEED)
    rows: list[dict[str, Any]] = []
    good = CASES - ERRORS - NEGATED - PLAIN_WRONG
    for i in range(CASES):
        term = TERMS[i % len(TERMS)]
        if i < good:
            kind = "ok"
        elif i < good + NEGATED:
            kind = "negated"
        elif i < good + NEGATED + PLAIN_WRONG:
            kind = "plain"
        else:
            kind = "error"
        row: dict[str, Any] = {"id": i + 1, "expected": term, "error": None}
        row["question"] = f"What is the limit for item {i + 1}?"
        if kind == "ok":
            row["answer"] = f"You have {term} for this."
        elif kind == "negated":
            row["answer"] = f"That is not {term}, it is shorter."
        elif kind == "plain":
            row["answer"] = "Please contact support for the details."
        else:
            row["answer"], row["error"] = None, "timeout"
        rows.append(row)
    rng.shuffle(rows)
    return rows


def _passes(code: str) -> Any:
    space: dict[str, Any] = {}
    exec(code, space)  # our own constant above, never learner code
    return space["passes"]


def _rates() -> tuple[float, float, int, int]:
    cases = _cases()
    buggy, fixed = _passes(GRADE_BUGGY), _passes(GRADE_FIXED)
    graded = [c for c in cases if c["error"] is None]
    dashboard = sum(buggy(c["answer"], c["expected"]) for c in graded) / len(graded)
    honest = sum(fixed(c["answer"], c["expected"]) for c in graded) / len(cases)
    false_passes = sum(
        buggy(c["answer"], c["expected"]) and not fixed(c["answer"], c["expected"]) for c in graded
    )
    return round(dashboard, 3), round(honest, 3), false_passes, len(cases) - len(graded)


def files() -> tuple[dict[str, str], dict[str, str]]:
    shared = {
        "README.md": README,
        "src/__init__.py": "",
        "tests/test_eval.py": TESTS,
        "data/cases.json": json.dumps(_cases(), indent=0),
    }
    starter = {**shared, "src/grade.py": GRADE_BUGGY, "src/report.py": REPORT_BUGGY}
    reference = {**shared, "src/grade.py": GRADE_FIXED, "src/report.py": REPORT_FIXED}
    return starter, reference


def tickets() -> list[Ticket]:
    return kit.tickets(
        "HI",
        [
            kit.TicketSpec(
                "Some passing answers look wrong",
                "A reviewer read a few answers the grader passed and says the assistant told "
                "the customer the opposite of the right thing. Work out how the grader decides "
                "an answer is right and make it stop passing answers that deny the fact.",
                (
                    "An answer that denies the expected fact does not pass",
                    "Capital letters do not change the result",
                ),
                ("llm-evaluation", "python"),
            ),
            kit.TicketSpec(
                "The dashboard score looks too good",
                "The dashboard reports 88% but a few test questions never got an answer at all. "
                "Make the dashboard say what share of ALL the test questions were answered "
                "correctly, and show how many had no answer.",
                (
                    "Questions with no answer count against the score",
                    "The dashboard shows how many questions had no answer",
                ),
                ("llm-evaluation", "data-analysis"),
            ),
            kit.REGRESSION,
        ],
    )


def rubric() -> list[Criterion]:
    return kit.rubric(
        [
            kit.CriterionSpec(
                "llm-evaluation",
                0.35,
                "Trusts the 88%.",
                "Fixes one number but not why it was too high.",
                "Finds both causes, measures the score before and after, and says how sure it is.",
                ("denied answers fail", "no-answer questions counted"),
            ),
            kit.CriterionSpec(
                "data-analysis",
                0.20,
                "Never looks at the rows.",
                "Looks at a few rows.",
                "Counts each kind of failure and shows them.",
                ("failures counted by kind",),
            ),
            kit.CriterionSpec(
                "python",
                0.20,
                "Changes that break the grader.",
                "Fixes the bug but not the capital-letter case.",
                "Small, readable changes with edge cases handled.",
                ("tests/test_eval.py passes",),
            ),
            kit.testing_criterion(0.25),
        ]
    )


PLANTED = [
    "grade.passes passes any answer that contains the expected phrase, even when it denies it",
    "report.summary leaves out questions with no answer, so failures cannot lower the score",
]


def metrics() -> dict[str, float]:
    dashboard, honest, false_passes, errors = _rates()
    return {
        "dashboard_claims": dashboard,
        "honest_pass_rate": honest,
        "false_passes": float(false_passes),
        "no_answer_questions": float(errors),
    }


def internship() -> Internship:
    people = [
        kit.Person(
            "ines",
            "Ines Okafor",
            "Head of AI",
            "Warm, direct, busy. Cares what the intern can tell Friday's launch review and "
            "about small, safe changes. Asks 'what do we know, and how sure are we?'. Does "
            "not read code.",
        ),
        kit.Person("callum", "Callum Reyes", "Senior ML Engineer", kit.REVIEWER_PERSONA),
        kit.Person(
            "dana",
            "Dana Whitlock",
            "Head of Customer Support",
            "Not technical. Her agents have seen the assistant tell people the opposite of "
            "the policy, and she is nervous about the launch. Gives examples, not causes.",
        ),
    ]
    return kit.week(
        people,
        ["HI-101", "HI-102", "HI-103"],
        welcome=(
            "Welcome to Halden! The launch review is on Friday and the dashboard says the "
            "assistant is right 88% of the time. Dana is not convinced. Callum is your point "
            "of contact for the code. Say hi to both."
        ),
        stakeholder=(
            "Hi, Dana from support. My agents keep finding the assistant telling customers "
            "the opposite of our policy, but the dashboard says it is almost always right. "
            "Could both be true?"
        ),
        nudge=kit.NUDGE,
        summary=(
            "I present to the launch review tomorrow. In a few plain sentences, can you write "
            "to me: can we trust the 88%, what was wrong, and how sure are you? Send it as a "
            "message in this chat."
        ),
        retro=kit.RETRO,
    )
