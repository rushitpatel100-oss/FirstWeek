"""A hand-written practice project for the Data Scientist role (ADR 0029).

Needs no model call and no library beyond the standard one. The project: the readout of an A/B
test of a new checkout page at a fictional grocer. The dashboard says the new page lifts
conversion by about 15%. Two realistic mistakes explain it: conversion is counted per session
(and the new page has fewer sessions per shopper), and the readout gives a lift with no
confidence interval, so nobody can see it is within the noise."""

import json
import math
import random

from firstweek_core.contracts import Criterion, Internship, Ticket
from firstweek_simulation import demo_kit as kit

SEED = 35
USERS_PER_ARM = 300
P_CONTROL = 0.20
P_NEW = 0.21

STATS_BUGGY = '''"""Conversion for one arm of the test."""


def conversion(rows, arm):
    chosen = [r for r in rows if r["arm"] == arm]
    return sum(r["orders"] for r in chosen) / sum(r["sessions"] for r in chosen)
'''
STATS_FIXED = '''"""Conversion for one arm of the test."""


def conversion(rows, arm):
    """The share of shoppers in the arm who ordered at least once."""
    chosen = [r for r in rows if r["arm"] == arm]
    return sum(r["orders"] > 0 for r in chosen) / len(chosen)
'''
REPORT_BUGGY = '''"""The numbers on the weekly experiment dashboard."""

import json

from src.stats import conversion


def readout(path="data/users.json"):
    rows = json.load(open(path))
    control, new = conversion(rows, "control"), conversion(rows, "new")
    return {"control": round(control, 3), "new": round(new, 3), "lift": round(new / control - 1, 3)}


if __name__ == "__main__":
    print(readout())
'''
REPORT_FIXED = '''"""The numbers on the weekly experiment dashboard."""

import json
import math

from src.stats import conversion


def readout(path="data/users.json"):
    rows = json.load(open(path))
    control, new = conversion(rows, "control"), conversion(rows, "new")
    n_control = sum(r["arm"] == "control" for r in rows)
    n_new = sum(r["arm"] == "new" for r in rows)
    se = math.sqrt(control * (1 - control) / n_control + new * (1 - new) / n_new)
    low, high = (new - control) - 1.96 * se, (new - control) + 1.96 * se
    return {
        "control": round(control, 3),
        "new": round(new, 3),
        "lift": round(new / control - 1, 3),
        "difference_ci": [round(low, 3), round(high, 3)],
        "significant": low > 0 or high < 0,
    }


if __name__ == "__main__":
    print(readout())
'''
README = """# Checkout experiment

`data/users.json` has one row per shopper in the test of the new checkout page: their arm
(`control` or `new`), how many sessions they had and how many orders they placed.
`python -m src.report` prints the readout shown on the weekly experiment dashboard.

Run the tests with `python -m pytest`.
"""
TESTS = """import json
import math

from src.report import readout
from src.stats import conversion


def test_conversion_is_the_share_of_shoppers_who_ordered():
    rows = [
        {"arm": "new", "sessions": 5, "orders": 2},
        {"arm": "new", "sessions": 1, "orders": 0},
        {"arm": "new", "sessions": 1, "orders": 0},
        {"arm": "new", "sessions": 1, "orders": 1},
        {"arm": "control", "sessions": 9, "orders": 0},
    ]
    assert conversion(rows, "new") == 0.5
    assert conversion(rows, "control") == 0.0


def test_the_readout_gives_a_confidence_interval_and_says_whether_it_is_significant():
    rows = json.load(open("data/users.json"))
    result = readout()
    control, new = conversion(rows, "control"), conversion(rows, "new")
    n = {a: sum(r["arm"] == a for r in rows) for a in ("control", "new")}
    se = math.sqrt(control * (1 - control) / n["control"] + new * (1 - new) / n["new"])
    low, high = (new - control) - 1.96 * se, (new - control) + 1.96 * se
    assert result["difference_ci"] == [round(low, 3), round(high, 3)]
    assert result["significant"] == (low > 0 or high < 0)
"""
SCENARIO = (
    "Marlow Grocers tested a new checkout page on half of its online shoppers. The weekly "
    "experiment dashboard says it lifts conversion by about 15%, and the product team wants to "
    "roll it out to everyone on Monday. Finance asks whether the lift is real before the "
    "engineering team spends a month migrating. Your first week is about finding out what the "
    "test actually shows."
)
CONTEXT = (
    "Marlow is an online grocer with about 250 staff and a data team of five. Every big change "
    "to the shop is decided from an experiment dashboard, so a wrong number there becomes a "
    "wrong decision for hundreds of thousands of shoppers."
)


def users() -> list[dict[str, int | str]]:
    rng = random.Random(SEED)
    rows: list[dict[str, int | str]] = []
    for arm, p, sessions in (("control", P_CONTROL, (1, 2, 3, 4)), ("new", P_NEW, (1, 2, 3))):
        for i in range(USERS_PER_ARM):
            ordered = rng.random() < p
            rows.append(
                {
                    "user": f"{arm[0]}{i}",
                    "arm": arm,
                    "sessions": rng.choice(sessions),
                    "orders": rng.choice((1, 1, 2)) if ordered else 0,
                }
            )
    return rows


def _rate(rows: list[dict[str, int | str]], arm: str, per_user: bool) -> float:
    chosen = [r for r in rows if r["arm"] == arm]
    if per_user:
        return sum(int(r["orders"]) > 0 for r in chosen) / len(chosen)
    return sum(int(r["orders"]) for r in chosen) / sum(int(r["sessions"]) for r in chosen)


def starter_reading() -> float:
    rows = users()
    return _rate(rows, "new", False) / _rate(rows, "control", False) - 1


def truth() -> dict[str, float]:
    rows = users()
    control, new = _rate(rows, "control", True), _rate(rows, "new", True)
    se = math.sqrt(control * (1 - control) / USERS_PER_ARM + new * (1 - new) / USERS_PER_ARM)
    return {
        "lift": round(new / control - 1, 3),
        "ci_low": round(new - control - 1.96 * se, 3),
        "ci_high": round(new - control + 1.96 * se, 3),
    }


def files() -> tuple[dict[str, str], dict[str, str]]:
    shared = {
        "README.md": README,
        "src/__init__.py": "",
        "tests/test_stats.py": TESTS,
        "data/users.json": json.dumps(users(), indent=0),
    }
    starter = {**shared, "src/stats.py": STATS_BUGGY, "src/report.py": REPORT_BUGGY}
    reference = {**shared, "src/stats.py": STATS_FIXED, "src/report.py": REPORT_FIXED}
    return starter, reference


def tickets() -> list[Ticket]:
    return kit.tickets(
        "MG",
        [
            kit.TicketSpec(
                "The dashboard says +15%. Is the lift real?",
                "The product team wants to roll the new page out on Monday. Work out how the "
                "dashboard counts conversion and make it count what the business means: the "
                "share of shoppers who bought.",
                (
                    "Conversion is the share of shoppers in an arm who ordered at least once",
                    "The lift is recomputed from that conversion",
                ),
                ("statistics", "experimentation"),
            ),
            kit.TicketSpec(
                "A lift with no error bars",
                "Finance asked how sure we are. Add to the readout a 95% confidence interval for "
                "the difference between the arms, and say plainly whether the result is "
                "significant.",
                (
                    "The readout shows a 95% interval for the difference in conversion",
                    "The readout says whether the interval excludes zero",
                ),
                ("statistics", "data-analysis"),
            ),
            kit.REGRESSION,
        ],
    )


def rubric() -> list[Criterion]:
    return kit.rubric(
        [
            kit.CriterionSpec(
                "experimentation",
                0.30,
                "Trusts the headline number.",
                "Fixes the count without checking the unit.",
                "Counts shoppers, not sessions, and explains why the unit matters.",
                ("conversion counts shoppers who ordered",),
            ),
            kit.CriterionSpec(
                "statistics",
                0.30,
                "Reports a lift with no uncertainty.",
                "Adds an interval but does not explain it.",
                "Adds the interval, says it spans zero, and says what that means for Monday.",
                ("interval is reported", "significance is reported"),
            ),
            kit.CriterionSpec(
                "data-analysis",
                0.15,
                "Edits that break the readout.",
                "Fixes the code, does not look at the data.",
                "Looks at sessions per shopper in each arm and explains the gap.",
                ("tests/test_stats.py passes",),
            ),
            kit.testing_criterion(0.25),
        ]
    )


PLANTED = [
    "stats.conversion divides orders by sessions, and the new page has fewer sessions per shopper",
    "report.readout gives a lift with no confidence interval, so the noise is invisible",
]


def metrics() -> dict[str, float]:
    fair = truth()
    return {"dashboard_claims": round(starter_reading(), 3), **fair}


def internship() -> Internship:
    people = [
        kit.Person(
            "dana",
            "Dana Whitfield",
            "Head of Data",
            "Warm, direct, busy. Cares what the intern can say to the product team on Friday "
            "and about small, safe changes. Asks 'what do we know, and how sure are we?'. Does "
            "not read code.",
        ),
        kit.Person("kofi", "Kofi Mensah", "Senior Data Scientist", kit.REVIEWER_PERSONA),
        kit.Person(
            "lena",
            "Lena Brandt",
            "Product Manager, Checkout",
            "Not technical. Wants to ship the new page on Monday and has already told her "
            "boss it won. Pushes for a yes or no, gives examples and deadlines, not causes.",
        ),
    ]
    return kit.week(
        people,
        ["MG-101", "MG-102", "MG-103"],
        welcome=(
            "Welcome to Marlow! The thing on my mind this week: the dashboard says the new "
            "checkout page lifts conversion by about 15%, and finance is asking whether to "
            "believe it. Kofi is your point of contact for the code. Say hi to both."
        ),
        stakeholder=(
            "Hi, Lena from the checkout team. We want to roll the new page out on Monday. "
            "The dashboard says +15% and I would like a clean yes. Finance keeps asking how "
            "sure we are, though, and I am not sure what to tell them."
        ),
        nudge=kit.NUDGE,
        summary=(
            "I meet the product team tomorrow. In a few plain sentences, can you write to me: "
            "should we roll out on Monday, what was wrong with the number, and how sure are "
            "you? Send it as a message in this chat."
        ),
        retro=kit.RETRO,
    )
