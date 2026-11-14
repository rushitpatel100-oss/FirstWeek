"""A hand-written practice project for the AI Product Manager role (ADR 0029).

Needs no model call and no library beyond the standard one. The project: the numbers behind a
launch decision for an AI support assistant at a fictional bank. The dashboard says it resolves
78% of conversations at about 1.60 each, so the launch looks like an easy yes. Two realistic
mistakes explain it: every conversation that was not escalated is counted as resolved (including
the ones where the customer just left), and cost per resolution divides by all conversations
instead of the resolved ones."""

import json
import random

from firstweek_core.contracts import Criterion, Internship, Ticket
from firstweek_simulation import demo_kit as kit

SEED = 9
CONFIRMED, REJECTED, ESCALATED, ABANDONED = 92, 20, 44, 44  # 200 conversations
HUMAN_COST = 4.50
MIN_RATE = 0.60
MAX_COST_SHARE = 0.50  # launch only if the assistant costs at most half of a human

METRICS_BUGGY = '''"""Which conversations the assistant resolved."""


def resolved(rows):
    return [r for r in rows if not r["escalated"]]


def resolution_rate(rows):
    return len(resolved(rows)) / len(rows)
'''
METRICS_FIXED = '''"""Which conversations the assistant resolved."""


def resolved(rows):
    """Only those where the customer confirmed that their problem was solved."""
    return [r for r in rows if r["user_confirmed"] is True]


def resolution_rate(rows):
    return len(resolved(rows)) / len(rows)
'''
COST_BUGGY = '''"""What a resolution costs."""


def cost_per_resolution(rows):
    return sum(r["cost"] for r in rows) / len(rows)
'''
COST_FIXED = '''"""What a resolution costs."""

from src.metrics import resolved


def cost_per_resolution(rows):
    """Everything the assistant cost, divided by the conversations it actually resolved."""
    done = resolved(rows)
    return sum(r["cost"] for r in rows) / len(done) if done else float("inf")
'''
REPORT = '''"""The launch readout the leadership team sees."""

import json

from src.cost import cost_per_resolution
from src.metrics import resolution_rate

HUMAN_COST = 4.50
MIN_RATE = 0.60
MAX_COST_SHARE = 0.50


def readout(path="data/conversations.json"):
    rows = json.load(open(path))
    rate, cost = resolution_rate(rows), cost_per_resolution(rows)
    return {
        "resolution_rate": round(rate, 3),
        "cost_per_resolution": round(cost, 2),
        "launch": rate >= MIN_RATE and cost <= HUMAN_COST * MAX_COST_SHARE,
    }


if __name__ == "__main__":
    print(readout())
'''
README = """# Assistant launch readout

`data/conversations.json` has a month of the assistant's conversations: whether it was handed to a
human (`escalated`), whether the customer confirmed the problem was solved (`user_confirmed`:
true, false, or null if they just left) and what the conversation cost. `python -m src.report`
prints the readout leadership uses to decide on a launch: go only if at least 60% of
conversations are resolved and a resolution costs at most half of what a human agent costs (4.50).

Run the tests with `python -m pytest`.
"""
TESTS = """from src.cost import cost_per_resolution
from src.metrics import resolution_rate


def row(escalated, confirmed, cost=1.0):
    return {"escalated": escalated, "user_confirmed": confirmed, "cost": cost}


def test_only_conversations_the_customer_confirmed_count_as_resolved():
    rows = [
        row(False, True),
        row(False, False),
        row(True, None),
        row(False, None),
        row(False, True),
    ]
    assert resolution_rate(rows) == 0.4


def test_cost_per_resolution_divides_by_what_was_resolved():
    rows = [row(False, True, 2.0), row(True, None, 8.0)]
    assert cost_per_resolution(rows) == 10.0
"""
SCENARIO = (
    "Lumen Bank is deciding whether to launch an AI assistant for customer support. The "
    "readout leadership will see on Friday says it resolves 78% of conversations at about 1.60 "
    "each, against 4.50 for a human agent, so the launch looks like an easy yes. The support "
    "team lead doubts the numbers and asks you, as the product manager, to check them before "
    "the meeting. Your first week is about finding out what the readout really says."
)
CONTEXT = (
    "Lumen is a mid-sized retail bank with about 1,200 staff. Support handles 80,000 "
    "conversations a month, and a launch decision commits a year of budget and tells customers "
    "the bank is changing how it helps them."
)


def conversations() -> list[dict[str, object]]:
    rng = random.Random(SEED)
    rows: list[dict[str, object]] = []
    for escalated, confirmed, count in (
        (False, True, CONFIRMED),
        (False, False, REJECTED),
        (True, None, ESCALATED),
        (False, None, ABANDONED),
    ):
        for _ in range(count):
            rows.append(
                {
                    "escalated": escalated,
                    "user_confirmed": confirmed,
                    "cost": round(rng.uniform(1.2, 2.0), 2),
                    "segment": rng.choice(["retail", "business"]),
                }
            )
    rng.shuffle(rows)
    for i, r in enumerate(rows, 1):
        r["id"] = i
    return rows


def files() -> tuple[dict[str, str], dict[str, str]]:
    shared = {
        "README.md": README,
        "src/__init__.py": "",
        "src/report.py": REPORT,
        "tests/test_readout.py": TESTS,
        "data/conversations.json": json.dumps(conversations(), indent=0),
    }
    starter = {**shared, "src/metrics.py": METRICS_BUGGY, "src/cost.py": COST_BUGGY}
    reference = {**shared, "src/metrics.py": METRICS_FIXED, "src/cost.py": COST_FIXED}
    return starter, reference


def tickets() -> list[Ticket]:
    return kit.tickets(
        "LB",
        [
            kit.TicketSpec(
                "Is 78% resolved really resolved?",
                "Support says many 'resolved' conversations ended with the customer simply "
                "leaving. Work out how the readout decides a conversation was resolved and make "
                "it count only those the customer confirmed.",
                (
                    "Only conversations the customer confirmed count as resolved",
                    "The resolution rate is recomputed from that",
                ),
                ("product-sense", "data-analysis"),
            ),
            kit.TicketSpec(
                "The cost per resolution looks too good",
                "Finance cannot reproduce 1.60 per resolution. Work out what it is divided by "
                "and make it the cost of everything the assistant handled, divided by what it "
                "actually resolved. Then say whether the launch rule still passes.",
                (
                    "Cost per resolution divides total cost by resolved conversations",
                    "The readout's launch verdict uses the corrected numbers",
                ),
                ("data-analysis", "stakeholder-communication"),
            ),
            kit.REGRESSION,
        ],
    )


def rubric() -> list[Criterion]:
    return kit.rubric(
        [
            kit.CriterionSpec(
                "product-sense",
                0.30,
                "Accepts the 78% because it is the dashboard's.",
                "Fixes the definition without asking what 'resolved' means to a customer.",
                "Defines resolved from the customer's side and explains why leaving is not a win.",
                ("only confirmed conversations count as resolved",),
            ),
            kit.CriterionSpec(
                "data-analysis",
                0.30,
                "Edits that break the readout.",
                "Fixes one of the two numbers.",
                "Fixes both numbers, checks one by hand, and re-reads the launch rule.",
                ("cost is divided by resolved conversations",),
            ),
            kit.CriterionSpec(
                "stakeholder-communication",
                0.15,
                "Says 'the numbers were wrong' with no detail.",
                "Reports the new numbers without a recommendation.",
                "Says what changed, what it means for the launch, and what is still unknown.",
                ("tests/test_readout.py passes",),
            ),
            kit.testing_criterion(0.25),
        ]
    )


PLANTED = [
    "metrics.resolved counts every conversation that was not escalated, including abandoned ones",
    "cost.cost_per_resolution divides by all conversations, not by the resolved ones",
]


def metrics() -> dict[str, float]:
    rows = conversations()
    total = len(rows)
    cost = sum(float(str(r["cost"])) for r in rows)
    shown_rate = sum(not r["escalated"] for r in rows) / total
    true_rate = sum(r["user_confirmed"] is True for r in rows) / total
    true_cost = cost / sum(r["user_confirmed"] is True for r in rows)
    return {
        "dashboard_resolution_rate": round(shown_rate, 3),
        "dashboard_cost_per_resolution": round(cost / total, 2),
        "resolution_rate": round(true_rate, 3),
        "cost_per_resolution": round(true_cost, 2),
        "launch_at_dashboard": float(
            shown_rate >= MIN_RATE and cost / total <= HUMAN_COST * MAX_COST_SHARE
        ),
        "launch": float(true_rate >= MIN_RATE and true_cost <= HUMAN_COST * MAX_COST_SHARE),
    }


def internship() -> Internship:
    people = [
        kit.Person(
            "amara",
            "Amara Osei",
            "Head of Product",
            "Warm, direct, busy. Cares what the intern can tell leadership on Friday and about "
            "small, safe changes. Asks 'what do we know, and how sure are we?'. Does not read "
            "code.",
        ),
        kit.Person("jun", "Jun Park", "Senior Data Analyst", kit.REVIEWER_PERSONA),
        kit.Person(
            "claire",
            "Claire Dubois",
            "Support Team Lead",
            "Not technical. Her agents pick up the conversations the assistant drops and she "
            "has seen customers leave frustrated. Gives examples and counts, not causes.",
        ),
    ]
    return kit.week(
        people,
        ["LB-101", "LB-102", "LB-103"],
        welcome=(
            "Welcome to Lumen! The thing on my mind this week: leadership will decide on the "
            "support assistant on Friday, and the readout says 78% resolved at 1.60 each. "
            "Claire does not believe it. Jun is your point of contact for the numbers. Say hi "
            "to both."
        ),
        stakeholder=(
            "Hi, Claire from support. In the transcripts I read, a lot of conversations just "
            "stop: the customer gives up and the assistant counts it as done. And somebody "
            "told me the cost figure is for each conversation, not for each problem solved. "
            "Can you check that?"
        ),
        nudge=kit.NUDGE,
        summary=(
            "I present the launch recommendation tomorrow. In a few plain sentences, can you "
            "write to me: should we launch, what was wrong with the readout, and how sure "
            "are you? Send it as a message in this chat."
        ),
        retro=kit.RETRO,
    )
