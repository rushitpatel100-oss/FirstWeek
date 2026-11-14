"""A hand-written practice project for the AI Data Engineer role (ADR 0029).

Needs no model call and no library beyond the standard one. The project: the nightly job that
builds a model's "latest spend per customer" feature table at a fictional media company. The
dashboard says every row loaded; the model team says the feature is stale for many customers.
Two realistic mistakes explain it: when a customer has several records the job keeps the first
it sees instead of the latest, and rows with a broken amount are dropped while the dashboard
divides by the rows that survived, so the load rate can only say 100%."""

import json
import random

from firstweek_core.contracts import Criterion, Internship, Ticket
from firstweek_simulation import demo_kit as kit

SEED = 7
CUSTOMERS = 40
EVENTS = 120
BAD = 8

CLEAN_BUGGY = '''"""One row per customer for the feature table."""


def latest(events):
    """Maps each customer to the record to use."""
    chosen = {}
    for event in events:
        chosen.setdefault(event["customer"], event)
    return chosen
'''
CLEAN_FIXED = '''"""One row per customer for the feature table."""


def latest(events):
    """Maps each customer to their most recent record."""
    chosen = {}
    for event in events:
        seen = chosen.get(event["customer"])
        if seen is None or event["ts"] > seen["ts"]:
            chosen[event["customer"]] = event
    return chosen
'''
REPORT_BUGGY = '''"""What the nightly pipeline dashboard shows."""

import json

from src.clean import latest


def valid(events):
    rows = []
    for event in events:
        try:
            rows.append({**event, "amount": float(event["amount"])})
        except (TypeError, ValueError):
            continue
    return rows


def summary(path="data/events.json"):
    events = json.load(open(path))
    rows = valid(events)
    return {
        "customers": len(latest(rows)),
        "load_rate": round(len(rows) / len(rows), 3),
        "rows_rejected": 0,
    }


if __name__ == "__main__":
    print(summary())
'''
REPORT_FIXED = '''"""What the nightly pipeline dashboard shows."""

import json

from src.clean import latest


def valid(events):
    rows = []
    for event in events:
        try:
            rows.append({**event, "amount": float(event["amount"])})
        except (TypeError, ValueError):
            continue
    return rows


def summary(path="data/events.json"):
    events = json.load(open(path))
    rows = valid(events)
    return {
        "customers": len(latest(rows)),
        "load_rate": round(len(rows) / len(events), 3),
        "rows_rejected": len(events) - len(rows),
    }


if __name__ == "__main__":
    print(summary())
'''
README = """# Customer spend feature

`data/events.json` has the night's records: one per customer update (`customer`, `ts` for when it
happened, and `amount`). `src/clean.py` picks the record to use for each customer; `src/report.py`
turns the night's file into the numbers on the pipeline dashboard.

Run the tests with `python -m pytest`.
"""
TESTS = """import json

from src.clean import latest
from src.report import summary


def test_the_most_recent_record_wins_whatever_order_they_arrive_in():
    events = [
        {"customer": "a", "ts": 1, "amount": 5.0},
        {"customer": "a", "ts": 3, "amount": 9.0},
        {"customer": "a", "ts": 2, "amount": 7.0},
        {"customer": "b", "ts": 1, "amount": 1.0},
    ]
    chosen = latest(events)
    assert chosen["a"]["amount"] == 9.0 and chosen["b"]["amount"] == 1.0


def test_the_dashboard_counts_the_rows_it_could_not_load():
    events = json.load(open("data/events.json"))

    def broken(e):
        try:
            float(e["amount"])
            return False
        except (TypeError, ValueError):
            return True

    bad = sum(broken(e) for e in events)
    result = summary()
    assert result["rows_rejected"] == bad
    assert result["load_rate"] == round(1 - bad / len(events), 3)
"""
SCENARIO = (
    "Corvid Media's nightly job builds the 'latest spend per customer' feature that a "
    "recommendation model reads. The pipeline dashboard says every row loaded, yet the model "
    "team says the feature looks stale for a lot of customers and recommendations feel out of "
    "date. Your first week is about finding out what the job really loads."
)
CONTEXT = (
    "Corvid is a streaming company with about 400 staff. The data platform team of seven feeds "
    "six models every night, so a quiet failure in one job turns into a worse product for "
    "millions of viewers the next morning."
)


def events() -> list[dict[str, object]]:
    rng = random.Random(SEED)
    rows: list[dict[str, object]] = []
    for i in range(EVENTS):
        customer = f"c{(i % CUSTOMERS) + 1}"
        rows.append(
            {
                "customer": customer,
                "ts": rng.randint(1, 1000),
                "amount": round(rng.uniform(5, 200), 2),
            }
        )
    for k, i in enumerate(rng.sample(range(EVENTS), BAD)):
        rows[i]["amount"] = None if k % 2 == 0 else "n/a"
    rng.shuffle(rows)
    return rows


def _usable(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    out = []
    for r in rows:
        try:
            out.append({**r, "amount": float(r["amount"])})  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
    return out


def _stale_customers() -> int:
    rows = _usable(events())
    first: dict[object, dict[str, object]] = {}
    newest: dict[object, dict[str, object]] = {}
    for r in rows:
        first.setdefault(r["customer"], r)
        if r["customer"] not in newest or r["ts"] > newest[r["customer"]]["ts"]:  # type: ignore[operator]
            newest[r["customer"]] = r
    return sum(first[c]["amount"] != newest[c]["amount"] for c in newest)


def files() -> tuple[dict[str, str], dict[str, str]]:
    shared = {
        "README.md": README,
        "src/__init__.py": "",
        "tests/test_pipeline.py": TESTS,
        "data/events.json": json.dumps(events(), indent=0),
    }
    starter = {**shared, "src/clean.py": CLEAN_BUGGY, "src/report.py": REPORT_BUGGY}
    reference = {**shared, "src/clean.py": CLEAN_FIXED, "src/report.py": REPORT_FIXED}
    return starter, reference


def tickets() -> list[Ticket]:
    return kit.tickets(
        "CM",
        [
            kit.TicketSpec(
                "The feature looks stale for many customers",
                "The model team says the 'latest spend' value is often an old one. Work out how "
                "the job chooses between several records for one customer and make it use the "
                "most recent one, whatever order the records arrive in.",
                (
                    "Each customer gets their most recent record",
                    "The result does not depend on the order of the file",
                ),
                ("data-engineering", "python"),
            ),
            kit.TicketSpec(
                "The dashboard says every row loaded",
                "Some rows in last night's file have no usable amount, yet the load rate says "
                "100%. Make the dashboard count the rows that could not be loaded, and show the "
                "true load rate.",
                (
                    "The dashboard shows how many rows were rejected",
                    "The load rate is loaded rows divided by all rows received",
                ),
                ("data-engineering", "observability"),
            ),
            kit.REGRESSION,
        ],
    )


def rubric() -> list[Criterion]:
    return kit.rubric(
        [
            kit.CriterionSpec(
                "data-engineering",
                0.30,
                "Edits that break the feature table.",
                "Picks the latest record but not for out-of-order files.",
                "Uses the timestamp, so arrival order cannot matter, and says why.",
                ("most recent record wins",),
            ),
            kit.CriterionSpec(
                "observability",
                0.30,
                "Trusts the 100%.",
                "Counts rejected rows but not in the rate.",
                "Counts rejected rows, fixes the rate, and asks where the bad rows come from.",
                ("rejected rows reported", "load rate uses all rows"),
            ),
            kit.CriterionSpec(
                "python",
                0.15,
                "Changes that crash on bad rows.",
                "Fixes the code without looking at the data.",
                "Looks at the rejected rows and describes what is wrong with them.",
                ("tests/test_pipeline.py passes",),
            ),
            kit.testing_criterion(0.25),
        ]
    )


PLANTED = [
    "clean.latest keeps the first record it sees for a customer, not the most recent one",
    "report.summary divides loaded rows by loaded rows, so the load rate is always 100%",
]


def metrics() -> dict[str, float]:
    return {
        "dashboard_claims": 1.0,
        "load_rate": round(1 - BAD / EVENTS, 3),
        "stale_customers": float(_stale_customers()),
        "customers": float(CUSTOMERS),
    }


def internship() -> Internship:
    people = [
        kit.Person(
            "mira",
            "Mira Castellanos",
            "Head of Data Platform",
            "Warm, direct, busy. Cares what the intern can tell the Friday platform review and "
            "about small, safe changes. Asks 'what do we know, and how sure are we?'. Does not "
            "read code.",
        ),
        kit.Person("sven", "Sven Lindgren", "Senior Data Engineer", kit.REVIEWER_PERSONA),
        kit.Person(
            "tess",
            "Tess Abara",
            "Recommendations Lead",
            "Not technical. Her team's model reads the feature every morning and has "
            "started recommending things customers bought months ago. Gives examples, not causes.",
        ),
    ]
    return kit.week(
        people,
        ["CM-101", "CM-102", "CM-103"],
        welcome=(
            "Welcome to Corvid! The thing on my mind this week: the pipeline dashboard says "
            "every row loaded last night, and Tess does not believe the data is right. Sven is "
            "your point of contact for the code. Say hi to both."
        ),
        stakeholder=(
            "Hi, Tess from recommendations. Our model keeps suggesting things customers "
            "stopped buying a long time ago, as if it saw their old spending. And the data "
            "team tells me everything loaded fine. Could both be true?"
        ),
        nudge=kit.NUDGE,
        summary=(
            "I present to the platform review tomorrow. In a few plain sentences, can you "
            "write to me: can we trust a dashboard that says 100%, what was wrong, and how "
            "sure are you? Send it as a message in this chat."
        ),
        retro=kit.RETRO,
    )
