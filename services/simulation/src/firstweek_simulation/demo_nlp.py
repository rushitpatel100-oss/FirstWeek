"""A hand-written practice project for the NLP Engineer role (ADR 0029).

Needs no model call and no library beyond the standard one: the "model" counts which words go
with which label. The project: a support-ticket router at a fictional software firm. In the
offline notebook it is about 90% accurate, but live tickets are routed wrongly far more often.
Two realistic mistakes explain it: training text is lowercased and stripped of punctuation but the
live path forgets to do the same, and a ticket with no word the model knows is still forced into
the first team's queue instead of being left for a person."""

import json
import random

from firstweek_core.contracts import Criterion, Internship, Ticket
from firstweek_simulation import demo_kit as kit

SEED = 6
TRAIN_PER_LABEL = 20
INCOMING = 40

VOCAB = {
    "billing": ["invoice", "charge", "refund", "payment", "card", "bill"],
    "login": ["password", "login", "locked", "account", "reset", "signin"],
    "outage": ["down", "outage", "error", "timeout", "slow", "unavailable"],
}
FILLER = ["the", "my", "is", "i", "cannot", "please", "again", "since", "this", "morning"]
OTHER = ["hello", "thanks", "anyone", "there", "question", "hi", "feedback", "great"]

TEXT = '''"""Cleaning ticket text the same way everywhere."""

import re


def normalise(text):
    return re.sub(r"[^a-z0-9 ]", "", text.lower())
'''
CLASSIFY_BUGGY = '''"""Counts which words go with which label."""

from collections import Counter


class Classifier:
    def __init__(self, tickets):
        self.counts = {}
        for ticket in tickets:
            self.counts.setdefault(ticket["label"], Counter()).update(ticket["text"].split())

    def classify(self, text):
        words = text.split()
        scores = {label: sum(c[w] for w in words) for label, c in self.counts.items()}
        return max(scores, key=scores.get)
'''
CLASSIFY_FIXED = '''"""Counts which words go with which label."""

from collections import Counter


class Classifier:
    def __init__(self, tickets):
        self.counts = {}
        for ticket in tickets:
            self.counts.setdefault(ticket["label"], Counter()).update(ticket["text"].split())

    def classify(self, text):
        """The team to route to, or "other" when no word is known (a person decides)."""
        words = text.split()
        scores = {label: sum(c[w] for w in words) for label, c in self.counts.items()}
        best = max(scores, key=scores.get)
        return best if scores[best] > 0 else "other"
'''
SERVE_BUGGY = '''"""What the live router calls for each new ticket."""


def predict(classifier, raw_text):
    return classifier.classify(raw_text)
'''
SERVE_FIXED = '''"""What the live router calls for each new ticket."""

from src.text import normalise


def predict(classifier, raw_text):
    return classifier.classify(normalise(raw_text))
'''
REPORT = '''"""Accuracy on tickets as they really arrive."""

import json

from src.classify import Classifier
from src.serve import predict


def live_accuracy(train="data/train.json", live="data/live.json"):
    classifier = Classifier(json.load(open(train)))
    tickets = json.load(open(live))
    right = sum(predict(classifier, t["text"]) == t["label"] for t in tickets)
    return round(right / len(tickets), 3)


if __name__ == "__main__":
    print({"live_accuracy": live_accuracy()})
'''
README = """# Ticket router

`data/train.json` has past tickets already cleaned (lowercase, no punctuation) with the team they
went to. `data/live.json` has recent tickets as customers typed them, with the right team.
`src/classify.py` counts which words go with which team; `src/serve.py` is what the live router
calls; `python -m src.report` prints the accuracy on the live tickets. In the offline notebook the
model scored about 90% on cleaned text.

Run the tests with `python -m pytest`.
"""
TESTS = """import json

from src.classify import Classifier
from src.serve import predict


def classifier():
    return Classifier(json.load(open("data/train.json")))


def test_the_model_routes_known_words_to_the_right_team():
    assert classifier().classify("password locked") == "login"
    assert classifier().classify("invoice refund") == "billing"


def test_live_text_is_cleaned_the_way_the_training_text_was():
    assert predict(classifier(), "My LOGIN is locked!! Please RESET my password.") == "login"
    assert predict(classifier(), "Invoice, refund?") == "billing"


def test_a_ticket_with_no_known_word_goes_to_a_person_not_a_queue():
    assert classifier().classify("hello anyone there thanks") == "other"
"""
SCENARIO = (
    "Quill Software routes incoming support tickets to the right team with a small text model. "
    "In the offline notebook it scored about 90%, but the support leads say tickets reach the "
    "wrong queue far more often than that, especially tickets that are short or polite. Your "
    "first week is about finding out why live tickets do worse than the notebook."
)
CONTEXT = (
    "Quill has about 180 staff and a support team of 25 across three queues. A wrongly routed "
    "ticket waits an extra day, and customers notice. The ML team has two people."
)


def _words(rng: random.Random, label: str, short: bool = False) -> list[str]:
    n = 1 if short else 3
    return rng.sample(VOCAB[label], n) + rng.sample(FILLER, n)


def train() -> list[dict[str, str]]:
    rng = random.Random(SEED)
    rows = []
    for label in VOCAB:
        for _ in range(TRAIN_PER_LABEL):
            words = _words(rng, label)
            rng.shuffle(words)
            rows.append({"text": " ".join(words), "label": label})
    rng.shuffle(rows)
    return rows


def _dress(rng: random.Random, words: list[str]) -> str:
    """How a customer actually types it: capitals and punctuation."""
    out = [w.upper() if rng.random() < 0.45 else w for w in words]
    out[0] = out[0].capitalize()
    out[-1] += rng.choice(["!", ".", "?", "!!"])
    return " ".join(out)


def live() -> list[dict[str, str]]:
    rng = random.Random(SEED + 1)
    rows = []
    for i in range(INCOMING):
        label = list(VOCAB)[i % 3] if i % 10 != 9 else "other"
        words = rng.sample(OTHER, 3) if label == "other" else _words(rng, label, short=True)
        rng.shuffle(words)
        rows.append({"text": _dress(rng, words), "label": label})
    rng.shuffle(rows)
    return rows


def _norm(text: str) -> str:
    return "".join(c for c in text.lower() if c.isalnum() or c == " ")


def _accuracy(clean_live: bool, abstain: bool) -> float:
    counts: dict[str, dict[str, int]] = {}
    for t in train():
        for w in t["text"].split():
            counts.setdefault(t["label"], {}).setdefault(w, 0)
            counts[t["label"]][w] += 1
    right = 0
    tickets = live()
    for t in tickets:
        words = (_norm(t["text"]) if clean_live else t["text"]).split()
        scores = {label: sum(c.get(w, 0) for w in words) for label, c in counts.items()}
        best = max(scores, key=lambda k: scores[k])
        guess = best if (scores[best] > 0 or not abstain) else "other"
        right += guess == t["label"]
    return right / len(tickets)


def starter_reading() -> float:
    """The notebook: cleaned text, and no way to say 'other'."""
    return _accuracy(clean_live=True, abstain=False)


def files() -> tuple[dict[str, str], dict[str, str]]:
    shared = {
        "README.md": README,
        "src/__init__.py": "",
        "src/text.py": TEXT,
        "src/report.py": REPORT,
        "tests/test_router.py": TESTS,
        "data/train.json": json.dumps(train(), indent=0),
        "data/live.json": json.dumps(live(), indent=0),
    }
    starter = {**shared, "src/classify.py": CLASSIFY_BUGGY, "src/serve.py": SERVE_BUGGY}
    reference = {**shared, "src/classify.py": CLASSIFY_FIXED, "src/serve.py": SERVE_FIXED}
    return starter, reference


def tickets() -> list[Ticket]:
    return kit.tickets(
        "QS",
        [
            kit.TicketSpec(
                "The notebook says 90%. Live tickets do much worse",
                "The model scored well offline but live tickets are misrouted far more often. "
                "Compare what the model was taught with what it is given in production and make "
                "the live path treat text the way training did.",
                (
                    "Live ticket text is cleaned the same way as the training text",
                    "A shouty, punctuated ticket is routed like its plain version",
                ),
                ("nlp", "machine-learning"),
            ),
            kit.TicketSpec(
                "Tickets nobody can route end up in billing",
                "A hello or a thank-you contains no word the model knows, yet it lands in the "
                "first team's queue. Make the router say 'other' when it has no evidence, so a "
                "person looks at it.",
                (
                    "A ticket with no known word is routed to 'other'",
                    "Tickets with known words are routed as before",
                ),
                ("nlp", "model-serving"),
            ),
            kit.REGRESSION,
        ],
    )


def rubric() -> list[Criterion]:
    return kit.rubric(
        [
            kit.CriterionSpec(
                "nlp",
                0.30,
                "Retrains on more data and hopes.",
                "Cleans text in one place only.",
                "Finds that training and live text are treated differently, and fixes it once.",
                ("live text is cleaned like training text",),
            ),
            kit.CriterionSpec(
                "model-serving",
                0.30,
                "Trusts the notebook number.",
                "Fixes cleaning but forces a team on every ticket.",
                "Lets the router say it does not know, and explains why that beats a guess.",
                ("a ticket with no known word goes to other",),
            ),
            kit.CriterionSpec(
                "machine-learning",
                0.15,
                "Edits that break the model.",
                "Fixes the code without checking the data.",
                "Looks at live tickets against training tickets and says what differs.",
                ("tests/test_router.py passes",),
            ),
            kit.testing_criterion(0.25),
        ]
    )


PLANTED = [
    "serve.predict passes raw text to the model, which was trained on lowercase text with no "
    "punctuation",
    "classify.Classifier.classify returns the top label even when no word was known",
]


def metrics() -> dict[str, float]:
    return {
        "dashboard_claims": round(starter_reading(), 3),
        "live_accuracy_starter": round(_accuracy(clean_live=False, abstain=False), 3),
        "live_accuracy": round(_accuracy(clean_live=True, abstain=True), 3),
    }


def internship() -> Internship:
    people = [
        kit.Person(
            "owen",
            "Owen Barrett",
            "Head of Machine Learning",
            "Warm, direct, busy. Cares what the intern can tell the Friday support review and "
            "about small, safe changes. Asks 'what do we know, and how sure are we?'. Does not "
            "read code.",
        ),
        kit.Person("yuki", "Yuki Nakamura", "Senior NLP Engineer", kit.REVIEWER_PERSONA),
        kit.Person(
            "bea",
            "Bea Oyelaran",
            "Support Operations Lead",
            "Not technical. Her agents spend their mornings forwarding misrouted tickets "
            "and are sceptical of the bot. Gives examples and counts, not causes.",
        ),
    ]
    return kit.week(
        people,
        ["QS-101", "QS-102", "QS-103"],
        welcome=(
            "Welcome to Quill! The thing on my mind this week: the router scored about 90% in "
            "the notebook, and Bea says that is not what she sees. Yuki is your point of "
            "contact for the code. Say hi to both."
        ),
        stakeholder=(
            "Hi, Bea from support. My agents forward misrouted tickets all morning. The worst "
            "ones are the short, polite ones: a 'Hello, thanks!' goes to billing every time, "
            "and tickets typed in capitals seem to get lost too. Is that expected?"
        ),
        nudge=kit.NUDGE,
        summary=(
            "I present to the support review tomorrow. In a few plain sentences, can you write "
            "to me: why does the router do worse live than in the notebook, what did you "
            "change, and how sure are you? Send it as a message in this chat."
        ),
        retro=kit.RETRO,
    )
