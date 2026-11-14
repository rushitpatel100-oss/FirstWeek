"""A hand-written practice project for the MLOps Engineer role (ADR 0029).

Needs no model call and no library beyond the standard one. The project: the drift monitor of a
delivery-time model at a fictional logistics firm. It has shown green for twelve weeks while
operations say estimates keep getting worse. Two realistic mistakes explain it: each week is
compared with the week before (so slow drift never adds up to an alert), and a tidy-up step that
fills in a missing feature with its last value, so a broken feed looks healthy."""

import json
import random

from firstweek_core.contracts import Criterion, Internship, Ticket
from firstweek_simulation import demo_kit as kit

SEED = 2
WEEKS = 12
MISSING_WEEK = 2
DRIFT_PER_WEEK = 1.8  # order value, in currency units; the training std is 10

WEEKLY_BUGGY = '''"""Loading the weekly feature averages."""

import json

FEATURES = ["order_value", "distance_km"]


def load(path="data/weekly.json"):
    weeks = json.load(open(path))
    last = {}
    for week in weeks:
        for name in FEATURES:
            if week.get(name) is None:
                week[name] = last.get(name)  # keep the last known value
            last[name] = week[name]
    return weeks
'''
WEEKLY_FIXED = '''"""Loading the weekly feature averages."""

import json

FEATURES = ["order_value", "distance_km"]


def load(path="data/weekly.json"):
    return json.load(open(path))
'''
MONITOR_BUGGY = '''"""Has a feature drifted? Shifts are measured in training standard deviations."""

THRESHOLD = 0.5


def check(history, baseline):
    """`history` is the list of weeks so far; the last one is the week being checked."""
    week = history[-1]
    previous = history[-2] if len(history) > 1 else week
    alerts = []
    for name, stats in baseline.items():
        if week.get(name) is None or previous.get(name) is None:
            continue
        if abs(week[name] - previous[name]) / stats["std"] > THRESHOLD:
            alerts.append(name)
    return alerts
'''
MONITOR_FIXED = '''"""Has a feature drifted? Shifts are measured in training standard deviations."""

THRESHOLD = 0.5


def check(history, baseline):
    """`history` is the list of weeks so far; the last one is the week being checked."""
    week = history[-1]
    alerts = []
    for name, stats in baseline.items():
        if week.get(name) is None:
            alerts.append(f"{name} (missing)")
        elif abs(week[name] - stats["mean"]) / stats["std"] > THRESHOLD:
            alerts.append(name)
    return alerts
'''
REPORT = '''"""What the weekly model-health dashboard shows."""

import json

from src.monitor import check
from src.weekly import load


def first_alert_week(path="data/weekly.json", baseline_path="data/baseline.json"):
    baseline = json.load(open(baseline_path))
    weeks = load(path)
    for i, week in enumerate(weeks):
        if check(weeks[: i + 1], baseline):
            return week["week"]
    return None


if __name__ == "__main__":
    print({"first_alert_week": first_alert_week()})
'''
README = """# Delivery-time model health

The delivery-time model was trained on data summarised in `data/baseline.json` (mean and standard
deviation of each input). `data/weekly.json` has the weekly average of each input in production.
`src/monitor.py` decides whether an input has drifted; `python -m src.report` prints the week
the dashboard first showed an alert (nothing means green all quarter).

Run the tests with `python -m pytest`.
"""
TESTS = """import json

from src.monitor import check
from src.report import first_alert_week
from src.weekly import load

BASELINE = {"x": {"mean": 100, "std": 10}}


def week(n, value):
    return {"week": n, "x": value}


def test_slow_drift_adds_up_to_an_alert():
    history = [week(1, 100), week(2, 102), week(3, 104), week(4, 106)]
    assert check(history[:3], BASELINE) == []
    assert check(history, BASELINE) == ["x"]


def test_a_missing_input_is_an_alert_not_a_green_light():
    assert check([week(1, 100), week(2, None)], BASELINE) == ["x (missing)"]


def test_loading_does_not_invent_missing_values():
    weeks = load()
    gaps = [w["week"] for w in weeks if w.get("distance_km") is None]
    assert gaps == [2]
    assert first_alert_week() == min(gaps + [w["week"] for w in weeks if w["order_value"] > 105])
"""
SCENARIO = (
    "Kestrel Logistics predicts delivery times with a model, and a drift monitor is supposed to "
    "warn the team when the model's inputs stop looking like its training data. The monitor has "
    "shown green for twelve weeks, but operations say the estimates keep getting worse and "
    "customers are complaining about late parcels. Your first week is about finding out what "
    "the monitor is really watching."
)
CONTEXT = (
    "Kestrel moves about 40,000 parcels a day with a platform team of six. Dispatchers plan "
    "their routes from the model's estimates, so a model that has drifted and a monitor that "
    "stays quiet cost real money every day."
)


def baseline() -> dict[str, dict[str, float]]:
    return {"order_value": {"mean": 100, "std": 10}, "distance_km": {"mean": 8, "std": 3}}


def weekly() -> list[dict[str, float | int | None]]:
    rng = random.Random(SEED)
    rows: list[dict[str, float | int | None]] = []
    for n in range(1, WEEKS + 1):
        rows.append(
            {
                "week": n,
                "order_value": round(100 + DRIFT_PER_WEEK * n + rng.uniform(-0.3, 0.3), 2),
                "distance_km": None if n == MISSING_WEEK else round(8 + rng.uniform(-0.1, 0.1), 2),
            }
        )
    return rows


def _first_alert(drift_only: bool) -> int | None:
    base = baseline()
    for row in weekly():
        if row["distance_km"] is None and not drift_only:
            return int(row["week"] or 0)
        value = row["order_value"]
        if value is not None and abs(value - base["order_value"]["mean"]) / 10 > 0.5:
            return int(row["week"] or 0)
    return None


def files() -> tuple[dict[str, str], dict[str, str]]:
    shared = {
        "README.md": README,
        "src/__init__.py": "",
        "src/report.py": REPORT,
        "tests/test_monitor.py": TESTS,
        "data/baseline.json": json.dumps(baseline(), indent=0),
        "data/weekly.json": json.dumps(weekly(), indent=0),
    }
    starter = {**shared, "src/monitor.py": MONITOR_BUGGY, "src/weekly.py": WEEKLY_BUGGY}
    reference = {**shared, "src/monitor.py": MONITOR_FIXED, "src/weekly.py": WEEKLY_FIXED}
    return starter, reference


def tickets() -> list[Ticket]:
    return kit.tickets(
        "KL",
        [
            kit.TicketSpec(
                "The drift monitor has been green for twelve weeks",
                "Operations say delivery estimates are getting worse, yet the monitor has never "
                "alerted. Work out what it compares each week with, and make it measure drift "
                "from what the model was trained on.",
                (
                    "Each week is compared with the training baseline, not the previous week",
                    "A slow, steady drift ends in an alert",
                ),
                ("mlops", "observability"),
            ),
            kit.TicketSpec(
                "A broken feed should not look healthy",
                "One week an input stopped arriving and nobody noticed. Make sure a missing input "
                "is reported as an alert, and that loading the data never invents values.",
                (
                    "A missing input raises an alert that says which input",
                    "Loading the weekly data leaves gaps as gaps",
                ),
                ("observability", "machine-learning"),
            ),
            kit.REGRESSION,
        ],
    )


def rubric() -> list[Criterion]:
    return kit.rubric(
        [
            kit.CriterionSpec(
                "mlops",
                0.30,
                "Raises the threshold until alerts disappear.",
                "Fixes the reference point but cannot say why the old one hid drift.",
                "Compares with training data and explains how week-on-week checks miss slow drift.",
                ("slow drift ends in an alert",),
            ),
            kit.CriterionSpec(
                "observability",
                0.30,
                "Trusts the green dashboard.",
                "Fixes the alert but not the silent filling-in.",
                "Finds both ways the monitor stayed quiet and makes failure loud.",
                ("missing input alerts", "loader leaves gaps"),
            ),
            kit.CriterionSpec(
                "machine-learning",
                0.15,
                "Edits that break the monitor.",
                "Fixes the code without looking at the data.",
                "Looks at the weekly numbers and says when a human would have noticed.",
                ("tests/test_monitor.py passes",),
            ),
            kit.testing_criterion(0.25),
        ]
    )


PLANTED = [
    "monitor.check compares each week with the previous week, so slow drift never alerts",
    "weekly.load fills a missing input with its last value, so a broken feed looks healthy",
]


def metrics() -> dict[str, float]:
    return {
        "first_alert_week": float(_first_alert(drift_only=False) or 0),
        "first_drift_week": float(_first_alert(drift_only=True) or 0),
        "weeks": float(WEEKS),
    }


def internship() -> Internship:
    people = [
        kit.Person(
            "ines",
            "Ines Duarte",
            "Head of Platform",
            "Warm, direct, busy. Cares what the intern can tell the Friday reliability review "
            "and about small, safe changes. Asks 'what do we know, and how sure are we?'. Does "
            "not read code.",
        ),
        kit.Person("raj", "Raj Patel", "Senior MLOps Engineer", kit.REVIEWER_PERSONA),
        kit.Person(
            "wes",
            "Wes Okafor",
            "Dispatch Operations Lead",
            "Not technical. His dispatchers plan routes from the estimates and have been "
            "saying for weeks that they are off. Gives examples and counts of late parcels, "
            "not causes.",
        ),
    ]
    return kit.week(
        people,
        ["KL-101", "KL-102", "KL-103"],
        welcome=(
            "Welcome to Kestrel! The thing on my mind this week: the model-health dashboard "
            "has been green for a quarter, and Wes does not believe it. Raj is your point of "
            "contact for the code. Say hi to both."
        ),
        stakeholder=(
            "Hi, Wes from dispatch. Our estimates have been wrong more often since the spring "
            "and late parcels are up. Yet I am told the model is fine and nothing has alerted. "
            "Can something be fine and wrong at the same time?"
        ),
        nudge=kit.NUDGE,
        summary=(
            "I present to the reliability review tomorrow. In a few plain sentences, can you "
            "write to me: can we trust a green dashboard, what was wrong, and how sure are "
            "you? Send it as a message in this chat."
        ),
        retro=kit.RETRO,
    )
