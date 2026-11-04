"""A hand-written practice project for the AI Software Engineer role (ADR 0026).

Needs no model call. The project: a service that wraps a model provider's API with a cache and
retries. The dashboard says the cache saves most model calls, but finance sees no saving and
users on the premium model get cheap-model answers. Two realistic bugs (a cache key that ignores
the model, and a retry loop that retries everything and swallows the final failure) explain it.
The model API is a deterministic fake, so everything runs offline in the sandbox."""

import json
import random

from firstweek_core.contracts import (
    Colleague,
    Criterion,
    Internship,
    InternshipEvent,
    Ticket,
)

SEED = 5
PROMPTS = 20
REQUESTS = 60
BAD = 6  # requests with an empty prompt

API = '''"""A deterministic stand-in for a model provider's API."""


class ApiError(Exception):
    pass


class RateLimited(ApiError):
    """Temporary: asking again a moment later can work."""


class BadRequest(ApiError):
    """The request itself is wrong: asking again will fail the same way."""


class FakeModelAPI:
    def __init__(self, flaky=None):
        self.flaky = dict(flaky or {})  # prompt -> times to rate limit before answering
        self.calls = 0

    def complete(self, prompt, model):
        self.calls += 1
        if not prompt.strip():
            raise BadRequest("empty prompt")
        if self.flaky.get(prompt, 0) > 0:
            self.flaky[prompt] -= 1
            raise RateLimited("slow down")
        return f"[{model}] answer to: {prompt.strip()}"
'''
SERVICE_BUGGY = '''"""Adds a cache and retries around the model API."""

from src.api import FakeModelAPI


class CompletionService:
    def __init__(self, api: FakeModelAPI, retries: int = 3):
        self.api = api
        self.retries = retries
        self.cache: dict = {}
        self.lookups = 0
        self.hits = 0

    def complete(self, prompt: str, model: str):
        self.lookups += 1
        key = prompt.strip().lower()
        if key in self.cache:
            self.hits += 1
            return self.cache[key]
        for _ in range(self.retries):
            try:
                answer = self.api.complete(prompt, model)
                self.cache[key] = answer
                return answer
            except Exception:
                continue
        return None
'''
SERVICE_FIXED = '''"""Adds a cache and retries around the model API."""

from src.api import FakeModelAPI, RateLimited


class CompletionService:
    def __init__(self, api: FakeModelAPI, retries: int = 3):
        self.api = api
        self.retries = retries
        self.cache: dict = {}
        self.lookups = 0
        self.hits = 0

    def complete(self, prompt: str, model: str):
        self.lookups += 1
        key = (model, " ".join(prompt.lower().split()))
        if key in self.cache:
            self.hits += 1
            return self.cache[key]
        for attempt in range(self.retries):
            try:
                answer = self.api.complete(prompt, model)
            except RateLimited:
                if attempt == self.retries - 1:
                    raise
                continue
            self.cache[key] = answer
            return answer
'''
REPORT = '''import json

from src.api import ApiError, FakeModelAPI
from src.service import CompletionService


def summary(path="data/requests.json"):
    """The numbers the weekly platform dashboard shows."""
    requests = json.load(open(path))
    service = CompletionService(FakeModelAPI())
    for request in requests:
        try:
            service.complete(request["prompt"], request["model"])
        except ApiError:
            pass
    return {"requests": len(requests), "hit_rate": round(service.hits / len(requests), 3)}


if __name__ == "__main__":
    print(summary())
'''
README = """# Completion service

`src/service.py` sits between our products and the model provider (`src/api.py`, a fake here):
it caches answers and retries. `data/requests.json` holds 60 recorded requests (prompt and model);
`python -m src.report` prints the cache numbers on the weekly platform dashboard.

Run the tests with `python -m pytest`.
"""
TESTS = """import json

import pytest

from src.api import BadRequest, FakeModelAPI, RateLimited
from src.report import summary
from src.service import CompletionService


def test_each_model_gets_its_own_answer():
    service = CompletionService(FakeModelAPI())
    assert service.complete("hello", "small").startswith("[small]")
    assert service.complete("hello", "large").startswith("[large]")


def test_a_repeat_of_the_same_request_is_served_from_the_cache():
    api = FakeModelAPI()
    service = CompletionService(api)
    service.complete("hello", "small")
    service.complete("  Hello ", "small")
    assert api.calls == 1 and service.hits == 1


def test_a_bad_request_is_an_error_and_is_asked_once():
    api = FakeModelAPI()
    service = CompletionService(api)
    with pytest.raises(BadRequest):
        service.complete("", "small")
    assert api.calls == 1


def test_a_rate_limited_request_is_retried():
    api = FakeModelAPI(flaky={"hello": 2})
    assert CompletionService(api).complete("hello", "small").startswith("[small]")
    assert api.calls == 3


def test_running_out_of_retries_raises_instead_of_returning_nothing():
    api = FakeModelAPI(flaky={"hello": 9})
    with pytest.raises(RateLimited):
        CompletionService(api).complete("hello", "small")


def test_the_hit_rate_matches_a_hand_count_on_the_real_requests():
    requests = json.load(open("data/requests.json"))
    seen, hits = set(), 0
    for r in requests:
        if not r["prompt"].strip():
            continue
        key = (r["model"], " ".join(r["prompt"].lower().split()))
        hits += key in seen
        seen.add(key)
    assert summary()["hit_rate"] == round(hits / len(requests), 3)
"""
SCENARIO = (
    "Relay Systems runs an internal service that sits between its products and a model provider. "
    "It caches answers and retries failures. The weekly platform dashboard says the cache saves "
    "most model calls, but finance sees no drop in the bill, and a team using the premium model "
    "reports answers that read like the cheap model's. Your first week is about finding out "
    "what the service is really doing."
)
CONTEXT = (
    "Relay has about 120 staff and a six-person platform team. Every product team reaches the "
    "model provider through this service, so a wrong answer or a wasted call is repeated across "
    "the company."
)


def requests() -> list[dict[str, str]]:
    rng = random.Random(SEED)
    prompts = [f"Summarise document number {i} in one line." for i in range(1, PROMPTS + 1)]
    out = [
        {"prompt": rng.choice(prompts), "model": rng.choice(["small", "large"])}
        for _ in range(REQUESTS - BAD)
    ]
    for _ in range(BAD):
        out.insert(rng.randrange(len(out) + 1), {"prompt": "", "model": "small"})
    return out


def _norm(prompt: str) -> str:
    return " ".join(prompt.lower().split())


def truth() -> float:
    rows, seen, hits = requests(), set(), 0
    for r in rows:
        if not r["prompt"].strip():
            continue
        key = (r["model"], _norm(r["prompt"]))
        hits += key in seen
        seen.add(key)
    return hits / len(rows)


def starter_reading() -> float:
    """What the buggy dashboard reports: the model is ignored, so any repeat prompt is a hit."""
    rows, seen, hits = requests(), set(), 0
    for r in rows:
        if not r["prompt"].strip():
            continue
        hits += _norm(r["prompt"]) in seen
        seen.add(_norm(r["prompt"]))
    return hits / len(rows)


def files() -> tuple[dict[str, str], dict[str, str]]:
    shared = {
        "README.md": README,
        "src/__init__.py": "",
        "src/api.py": API,
        "src/report.py": REPORT,
        "tests/test_service.py": TESTS,
        "data/requests.json": json.dumps(requests(), indent=0),
    }
    return {**shared, "src/service.py": SERVICE_BUGGY}, {**shared, "src/service.py": SERVICE_FIXED}


def tickets() -> list[Ticket]:
    return [
        Ticket(
            key="RS-101",
            title="The dashboard says the cache saves most calls. Does it?",
            description=(
                "Finance sees no drop in the model bill, and the premium-model team says its "
                "answers look like the cheap model's. Work out how the cache decides two "
                "requests are the same and fix it so the hit rate matches a hand count."
            ),
            acceptance_criteria=[
                "The same prompt sent to a different model is not a cache hit",
                "The dashboard hit rate equals a hand count on data/requests.json",
            ],
            task_type="code",
            due_day=1,
            skills=["backend-development", "observability"],
        ),
        Ticket(
            key="RS-102",
            title="Bad requests and rate limits are treated the same",
            description=(
                "A request that can never work is asked three times, and when the provider keeps "
                "saying 'slow down' the caller just gets nothing back. Retry only what can "
                "succeed later, and make a final failure visible to the caller."
            ),
            acceptance_criteria=[
                "A bad request is attempted once and raises",
                "A rate-limited request is retried, and raises if it never succeeds",
            ],
            task_type="code",
            due_day=2,
            skills=["backend-development", "performance-optimization"],
        ),
        Ticket(
            key="RS-103",
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
            skills=["testing", "performance-optimization"],
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
        crit("backend-development", 0.30,
             _anchors("Edits that break other code.", "Fixes one of the two causes cleanly.",
                      "Fixes both causes with small, clear changes."),
             ["tests/test_service.py passes", "no test regressions"]),
        crit("observability", 0.20,
             _anchors("Trusts the dashboard number.", "Fixes the number without checking it.",
                      "Checks the number by hand and explains the gap."),
             ["hit rate equals the hand count"]),
        crit("performance-optimization", 0.25,
             _anchors("Keeps wasting calls.", "Stops retrying bad requests but loses retries.",
                      "Retries only what can succeed and explains the cost of the rest."),
             ["a bad request is attempted once", "a rate limit is retried"]),
        crit("testing", 0.25,
             _anchors("No new test.", "A test that passes before and after the fix.",
                      "A focused test that fails on the old code and passes on the fix."),
             ["new test fails on the starter", "new test passes on the reference"]),
    ]  # fmt: skip


PLANTED = [
    "service.complete builds its cache key from the prompt alone, so the model is ignored",
    "service.complete retries every exception and returns None after the last, hiding failures",
]


def metrics() -> dict[str, float]:
    return {"hit_rate": round(truth(), 3), "dashboard_claims": round(starter_reading(), 3)}


def internship() -> Internship:
    colleagues = [
        Colleague(
            key="jordan",
            name="Jordan Hale",
            role="Engineering Manager",
            persona=(
                "Warm, direct, busy. Cares what the intern can tell the platform review on "
                "Friday and about small, safe changes. Asks 'what do we know, and how sure "
                "are we?'. Does not read code."
            ),
        ),
        Colleague(
            key="mei",
            name="Mei Tanaka",
            role="Staff Engineer",
            persona=(
                "Precise and kind. Reviews carefully, likes small changes and tests that fail "
                "for the right reason. Answers with a hint or a question, never the fix."
            ),
        ),
        Colleague(
            key="carlos",
            name="Carlos Ruiz",
            role="Platform Finance Partner",
            persona=(
                "Not technical. Watches the model provider bill and a premium-model team's "
                "complaints. Frustrated that the dashboard promises savings that never show up. "
                "Gives numbers and examples, not causes."
            ),
        ),
    ]
    events = [
        InternshipEvent(
            day=1, kind="message", sender="jordan",
            text=(
                "Welcome to Relay! The one thing on my mind this week: the platform dashboard "
                "says our cache saves most model calls, and Carlos does not believe it. Mei is "
                "your point of contact for the code. Say hi to both."
            ),
        ),
        InternshipEvent(
            day=1, kind="ticket", sender="jordan", ticket="RS-101",
            text="RS-101 is on your board. Start there, and shout if anything is unclear.",
        ),
        InternshipEvent(
            day=2, kind="message", sender="carlos",
            text=(
                "Hi, Carlos from finance. The model bill has not moved since the cache shipped. "
                "One team on the premium model also says its answers feel cheaper. And last "
                "week's provider invoice shows a lot of failed requests. Could those be linked?"
            ),
        ),
        InternshipEvent(
            day=2, kind="ticket", sender="jordan", ticket="RS-102",
            text="Carlos's point deserves its own ticket: RS-102 is yours.",
        ),
        InternshipEvent(
            day=3, kind="message", sender="mei",
            text=(
                "Good progress. Before RS-103: tests are how this stays fixed. Keep the change "
                "small enough that I can review it over coffee."
            ),
        ),
        InternshipEvent(day=3, kind="ticket", sender="mei", ticket="RS-103",
                        text="RS-103 is on your board."),
        InternshipEvent(
            day=4, kind="message", sender="jordan",
            text=(
                "I present to the platform review tomorrow. In a few plain sentences, can you "
                "write to me: can we trust the dashboard, what was wrong, and how sure are you? "
                "Send it as a message in this chat."
            ),
        ),
        InternshipEvent(
            day=5, kind="meeting", sender="jordan",
            text=(
                "Friday retro: what went well, what you would do differently, and what you still "
                "do not know. Then I will write up how the week went."
            ),
        ),
    ]  # fmt: skip
    return Internship(colleagues=colleagues, events=events)
