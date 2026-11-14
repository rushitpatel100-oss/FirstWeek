"""A hand-written practice project for the ML Engineer role (ADR 0029).

Needs no model call and no ML library: the "model" is a small nearest-neighbour classifier in
plain Python, so it runs offline in the sandbox. The project: a model that flags customers likely
to pay their energy bill late, so the collections team can call them early. The dashboard says
91% accuracy, but collections finds the calls miss most late payers. Two realistic mistakes
explain it: the same customer's monthly rows land on both sides of the train/test split (so the
model has seen the answer), and the report only shows accuracy, which a model that always says
"on time" would also score well on."""

import json
import random

from firstweek_core.contracts import (
    Colleague,
    Criterion,
    Internship,
    InternshipEvent,
    Ticket,
)

SEED = 3
CUSTOMERS = 48
MONTHS = 5
LATE_SHARE = 0.25
TEST_FRACTION = 0.25
SPLIT_SEED = 0

DATA_PY = '''"""Loading the customer table."""

import json

FEATURES = ["tenure_months", "avg_bill", "support_calls"]


def load(path="data/customers.json"):
    with open(path) as f:
        return json.load(f)


def matrix(rows):
    return [[row[name] for name in FEATURES] for row in rows]


def labels(rows):
    return [row["late"] for row in rows]
'''
MODEL_PY = '''"""A tiny nearest-neighbour classifier: a row gets its closest known row's label."""


class NearestNeighbour:
    def fit(self, X, y):
        columns = list(zip(*X))
        self.mean = [sum(c) / len(c) for c in columns]
        self.std = [
            (sum((v - m) ** 2 for v in c) / len(c)) ** 0.5 or 1.0
            for c, m in zip(columns, self.mean)
        ]
        self.X = [self._scale(row) for row in X]
        self.y = list(y)
        return self

    def _scale(self, row):
        return [(v - m) / s for v, m, s in zip(row, self.mean, self.std)]

    def predict(self, X):
        out = []
        for row in X:
            point = self._scale(row)
            best = min(
                range(len(self.X)),
                key=lambda i: sum((a - b) ** 2 for a, b in zip(self.X[i], point)),
            )
            out.append(self.y[best])
        return out
'''
SPLIT_BUGGY = '''"""Train/test split."""

import random


def split(rows, test_fraction=0.25, seed=0):
    order = list(range(len(rows)))
    random.Random(seed).shuffle(order)
    cut = int(len(rows) * test_fraction)
    test = [rows[i] for i in order[:cut]]
    train = [rows[i] for i in order[cut:]]
    return train, test
'''
SPLIT_FIXED = '''"""Train/test split."""

import random


def split(rows, test_fraction=0.25, seed=0):
    """Whole customers go to one side, so the model is tested on people it has never seen."""
    ids = sorted({row["customer"] for row in rows})
    random.Random(seed).shuffle(ids)
    held_out = set(ids[: int(len(ids) * test_fraction)])
    test = [row for row in rows if row["customer"] in held_out]
    train = [row for row in rows if row["customer"] not in held_out]
    return train, test
'''
REPORT_BUGGY = '''"""The numbers the weekly dashboard shows."""

from src.data import labels, load, matrix
from src.model import NearestNeighbour
from src.split import split


def evaluate(path="data/customers.json"):
    train, test = split(load(path))
    model = NearestNeighbour().fit(matrix(train), labels(train))
    predicted = model.predict(matrix(test))
    correct = sum(p == y for p, y in zip(predicted, labels(test)))
    return {"accuracy": round(correct / len(test), 3)}


if __name__ == "__main__":
    print(evaluate())
'''
REPORT_FIXED = '''"""The numbers the weekly dashboard shows."""

from src.data import labels, load, matrix
from src.model import NearestNeighbour
from src.split import split


def evaluate(path="data/customers.json"):
    train, test = split(load(path))
    model = NearestNeighbour().fit(matrix(train), labels(train))
    predicted = model.predict(matrix(test))
    actual = labels(test)
    correct = sum(p == y for p, y in zip(predicted, actual))
    late = sum(actual)
    caught = sum(p == 1 and y == 1 for p, y in zip(predicted, actual))
    return {
        "accuracy": round(correct / len(test), 3),
        "baseline": round(1 - late / len(test), 3),  # always guessing "on time"
        "recall": round(caught / late, 3) if late else 0.0,
    }


if __name__ == "__main__":
    print(evaluate())
'''
README = """# Late-payment model

`src/model.py` is a small classifier. `data/customers.json` has five monthly rows for each of 48
customers (tenure, average bill, support calls) and whether that customer paid late (`late`: 1)
or on time (0). `python -m src.report` prints the numbers on the weekly dashboard. Collections
uses the model to decide whom to call before a bill is due.

Run the tests with `python -m pytest`.
"""
TESTS = """from src.data import labels, load, matrix
from src.model import NearestNeighbour
from src.report import evaluate
from src.split import split


def test_the_model_gives_a_row_the_label_of_its_closest_known_row():
    model = NearestNeighbour().fit([[0, 0, 0], [10, 10, 10]], [0, 1])
    assert model.predict([[1, 1, 1], [9, 9, 9]]) == [0, 1]


def test_no_customer_appears_on_both_sides_of_the_split():
    train, test = split(load())
    assert {r["customer"] for r in train}.isdisjoint({r["customer"] for r in test})
    assert len(train) + len(test) == len(load())


def test_the_report_says_what_always_guessing_on_time_would_score_and_how_many_late_it_catches():
    train, test = split(load())
    result = evaluate()
    actual = labels(test)
    assert result["baseline"] == round(1 - sum(actual) / len(actual), 3)
    model = NearestNeighbour().fit(matrix(train), labels(train))
    predicted = model.predict(matrix(test))
    caught = sum(p == 1 and y == 1 for p, y in zip(predicted, actual))
    assert result["recall"] == round(caught / sum(actual), 3)
"""
SCENARIO = (
    "Tern Energy sends a reminder call to customers a model says are likely to pay their bill "
    "late. The weekly dashboard says the model is 91% accurate, but the collections team finds "
    "that most of the customers who do pay late were never flagged, and keeps asking why the "
    "calls are not helping. Your first week is about finding out how good the model really is."
)
CONTEXT = (
    "Tern is a regional energy supplier with about 300 staff. The data science team has four "
    "people; the collections team of twelve acts on the model's list every Monday, so every "
    "wrong number on the dashboard turns into wasted calls and missed late payers."
)


def customers() -> list[dict[str, float]]:
    rng = random.Random(SEED)
    rows: list[dict[str, float]] = []
    for customer in range(1, CUSTOMERS + 1):
        late = int(rng.random() < LATE_SHARE)
        tenure = rng.uniform(3, 120)
        bill = rng.uniform(40, 140) + 6 * late
        calls = rng.uniform(0, 6) + 0.8 * late
        for _ in range(MONTHS):
            rows.append(
                {
                    "customer": customer,
                    "tenure_months": round(tenure + rng.uniform(-0.4, 0.4), 2),
                    "avg_bill": round(bill * rng.uniform(0.98, 1.02), 2),
                    "support_calls": round(max(0.0, calls + rng.uniform(-0.2, 0.2)), 2),
                    "late": late,
                }
            )
    return rows


def _fit_predict(train: list[dict[str, float]], test: list[dict[str, float]]) -> list[int]:
    names = ["tenure_months", "avg_bill", "support_calls"]
    columns = [[r[n] for r in train] for n in names]
    mean = [sum(c) / len(c) for c in columns]
    std = [
        (sum((v - m) ** 2 for v in c) / len(c)) ** 0.5 or 1.0
        for c, m in zip(columns, mean, strict=False)
    ]

    def scale(row: dict[str, float]) -> list[float]:
        return [(row[n] - m) / s for n, m, s in zip(names, mean, std, strict=False)]

    known = [(scale(r), int(r["late"])) for r in train]
    out = []
    for row in test:
        point = scale(row)
        out.append(
            min(known, key=lambda k: sum((a - b) ** 2 for a, b in zip(k[0], point, strict=False)))[
                1
            ]
        )
    return out


def _split(
    rows: list[dict[str, float]], by_customer: bool
) -> tuple[list[dict[str, float]], list[dict[str, float]]]:
    if not by_customer:
        order = list(range(len(rows)))
        random.Random(SPLIT_SEED).shuffle(order)
        cut = int(len(rows) * TEST_FRACTION)
        return [rows[i] for i in order[cut:]], [rows[i] for i in order[:cut]]
    ids = sorted({int(r["customer"]) for r in rows})
    random.Random(SPLIT_SEED).shuffle(ids)
    held = set(ids[: int(len(ids) * TEST_FRACTION)])
    return (
        [r for r in rows if int(r["customer"]) not in held],
        [r for r in rows if int(r["customer"]) in held],
    )


def _scores(by_customer: bool) -> dict[str, float]:
    train, test = _split(customers(), by_customer)
    predicted = _fit_predict(train, test)
    actual = [int(r["late"]) for r in test]
    late = sum(actual)
    caught = sum(p == 1 and y == 1 for p, y in zip(predicted, actual, strict=False))
    return {
        "accuracy": round(
            sum(p == y for p, y in zip(predicted, actual, strict=False)) / len(test), 3
        ),
        "baseline": round(1 - late / len(test), 3),
        "recall": round(caught / late, 3) if late else 0.0,
    }


def starter_reading() -> dict[str, float]:
    """What the dashboard shows today: whole rows are split at random."""
    return _scores(by_customer=False)


def truth() -> dict[str, float]:
    """What the model scores on customers it has never seen."""
    return _scores(by_customer=True)


def files() -> tuple[dict[str, str], dict[str, str]]:
    shared = {
        "README.md": README,
        "src/__init__.py": "",
        "src/data.py": DATA_PY,
        "src/model.py": MODEL_PY,
        "tests/test_model.py": TESTS,
        "data/customers.json": json.dumps(customers(), indent=0),
    }
    starter = {**shared, "src/split.py": SPLIT_BUGGY, "src/report.py": REPORT_BUGGY}
    reference = {**shared, "src/split.py": SPLIT_FIXED, "src/report.py": REPORT_FIXED}
    return starter, reference


def tickets() -> list[Ticket]:
    return [
        Ticket(
            key="TE-101",
            title="The dashboard says 91% accurate. Is it?",
            description=(
                "Collections says most customers who pay late are never on their Monday list. "
                "Work out how the model is being tested and make the test honest: it should "
                "score the model on customers it has not seen before."
            ),
            acceptance_criteria=[
                "No customer is on both sides of the train/test split",
                "The dashboard accuracy comes from customers the model has not seen",
            ],
            task_type="code",
            due_day=1,
            skills=["machine-learning", "statistics"],
        ),
        Ticket(
            key="TE-102",
            title="Accuracy alone hides who we miss",
            description=(
                "Only about a quarter of customers pay late, so a model that never flags "
                "anyone would still look good. Add to the report what that lazy guess would "
                "score, and how many of the customers who really pay late the model catches."
            ),
            acceptance_criteria=[
                "The report shows the score of always guessing 'on time'",
                "The report shows the share of late payers the model catches",
            ],
            task_type="code",
            due_day=2,
            skills=["statistics", "model-training"],
        ),
        Ticket(
            key="TE-103",
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
            skills=["testing", "machine-learning"],
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
        crit("machine-learning", 0.30,
             _anchors("Edits that break the pipeline.", "Fixes the test set, not how it is chosen.",
                      "Tests only on customers the model has never seen, and says why."),
             ["no customer is on both sides of the split"]),
        crit("statistics", 0.30,
             _anchors("Trusts one headline number.", "Adds a baseline but does not explain it.",
                      "Compares with the lazy guess, reports recall, and explains the gap."),
             ["baseline is reported", "recall is reported"]),
        crit("model-training", 0.15,
             _anchors("Changes the model without a reason.", "Leaves the model alone.",
                      "Leaves the model alone and explains what a fair test would show first."),
             ["tests/test_model.py passes"]),
        crit("testing", 0.25,
             _anchors("No new test.", "A test that passes before and after the fix.",
                      "A focused test that fails on the old code and passes on the fix."),
             ["new test fails on the starter", "new test passes on the reference"]),
    ]  # fmt: skip


PLANTED = [
    "split.split shuffles rows, so one customer's monthly rows land on both sides of the split",
    "report.evaluate returns accuracy only, with no baseline and no recall on late payers",
]


def metrics() -> dict[str, float]:
    seen, fair = starter_reading(), truth()
    return {
        "dashboard_claims": seen["accuracy"],
        "accuracy": fair["accuracy"],
        "baseline": fair["baseline"],
        "recall": fair["recall"],
    }


def internship() -> Internship:
    colleagues = [
        Colleague(
            key="nadia",
            name="Nadia Farouk",
            role="Head of Data Science",
            persona=(
                "Warm, direct, busy. Cares what the intern can tell the Friday ops review and "
                "about small, safe changes. Asks 'what do we know, and how sure are we?'. Does "
                "not read code."
            ),
        ),
        Colleague(
            key="tom",
            name="Tom Adeyemi",
            role="Senior ML Engineer",
            persona=(
                "Precise and kind. Reviews carefully, likes small changes and tests that fail "
                "for the right reason. Answers with a hint or a question, never the fix."
            ),
        ),
        Colleague(
            key="grace",
            name="Grace Lindqvist",
            role="Collections Team Lead",
            persona=(
                "Not technical. Her team phones the customers on the model's list every "
                "Monday and is frustrated that the calls reach people who would have paid anyway. "
                "Gives examples and counts, not causes."
            ),
        ),
    ]
    events = [
        InternshipEvent(
            day=1, kind="message", sender="nadia",
            text=(
                "Welcome to Tern! The thing on my mind this week: the dashboard says our "
                "late-payment model is 91% accurate, and Grace does not believe it. Tom is "
                "your point of contact for the code. Say hi to both."
            ),
        ),
        InternshipEvent(
            day=1, kind="ticket", sender="nadia", ticket="TE-101",
            text="TE-101 is on your board. Start there, and shout if anything is unclear.",
        ),
        InternshipEvent(
            day=2, kind="message", sender="grace",
            text=(
                "Hi, Grace from collections. Last month 40 customers paid late and only a "
                "handful were on our Monday list. We are spending the whole morning on people "
                "who pay anyway. Is the 91% even about the people we need to reach?"
            ),
        ),
        InternshipEvent(
            day=2, kind="ticket", sender="nadia", ticket="TE-102",
            text="Grace's point deserves its own ticket: TE-102 is yours.",
        ),
        InternshipEvent(
            day=3, kind="message", sender="tom",
            text=(
                "Good progress. Before TE-103: tests are how this stays fixed. Keep the change "
                "small enough that I can review it over coffee."
            ),
        ),
        InternshipEvent(day=3, kind="ticket", sender="tom", ticket="TE-103",
                        text="TE-103 is on your board."),
        InternshipEvent(
            day=4, kind="message", sender="nadia",
            text=(
                "I present to the ops review tomorrow. In a few plain sentences, can you write "
                "to me: can we trust the 91%, what was wrong, and how sure are you? Send it "
                "as a message in this chat."
            ),
        ),
        InternshipEvent(
            day=5, kind="meeting", sender="nadia",
            text=(
                "Friday retro: what went well, what you would do differently, and what you still "
                "do not know. Then I will write up how the week went."
            ),
        ),
    ]  # fmt: skip
    return Internship(colleagues=colleagues, events=events)
