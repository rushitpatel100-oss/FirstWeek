"""A hand-written practice project for the Agentic AI Engineer role (ADR 0026).

Like the GenAI one (ADR 0022) it needs no model call. The project: a travel-booking agent whose
nightly report is all green while customers say bookings fail. Two realistic bugs (a tool error
swallowed into an empty string, and a loop with no step limit) hide the truth; the report adds a
third by dropping runs that crash. The learner finds and fixes them, then writes a regression
test. The fake model is scripted, so everything runs offline in the sandbox."""

import json
import random

from firstweek_core.contracts import (
    Colleague,
    Criterion,
    Internship,
    InternshipEvent,
    Ticket,
)

SEED = 11
KINDS = ["good"] * 14 + ["recovered"] * 4 + ["failed"] * 6 + ["stuck"] * 6

TOOLS_BUGGY = '''"""Tools the agent can call. Each takes keyword arguments and returns text."""


class ToolError(Exception):
    pass


FLIGHTS = {
    ("LON", "NYC"): "BA117 09:00 GBP 420",
    ("LON", "PAR"): "EZY802 07:30 GBP 89",
    ("PAR", "ROM"): "AF1104 12:10 GBP 140",
}


def search_flights(origin, dest):
    if (origin, dest) not in FLIGHTS:
        raise ToolError(f"no flights {origin}->{dest}")
    return FLIGHTS[(origin, dest)]


def book(flight):
    return f"booked {flight}"


TOOLS = {"search_flights": search_flights, "book": book}


def call(name, args):
    """Runs a tool and returns its result as text."""
    try:
        return TOOLS[name](**args)
    except Exception:
        return ""
'''
TOOLS_FIXED = TOOLS_BUGGY.replace(
    """    try:
        return TOOLS[name](**args)
    except Exception:
        return ""
""",
    """    if name not in TOOLS:
        raise ToolError(f"unknown tool {name}")
    try:
        return TOOLS[name](**args)
    except TypeError as exc:
        raise ToolError(f"bad arguments for {name}: {exc}") from exc
""",
)
AGENT_BUGGY = '''"""The booking agent: the model picks tools until it answers."""

from src import tools

MAX_STEPS = 6


def run(model, goal):
    history = [{"role": "user", "content": goal}]
    steps = 0
    while True:
        action = model(history)
        steps += 1
        if action["type"] == "final":
            return {"status": "done", "answer": action["text"], "steps": steps}
        result = tools.call(action["tool"], action["args"])
        history.append({"role": "tool", "content": result})
'''
AGENT_FIXED = '''"""The booking agent: the model picks tools until it answers."""

from src import tools

MAX_STEPS = 6


def run(model, goal):
    history = [{"role": "user", "content": goal}]
    error = None
    for steps in range(1, MAX_STEPS + 1):
        action = model(history)
        if action["type"] == "final":
            status = "failed" if error else "done"
            return {"status": status, "answer": action["text"], "steps": steps}
        try:
            result = tools.call(action["tool"], action["args"])
            error = None
        except tools.ToolError as exc:
            result = f"ERROR: {exc}"
            error = str(exc)
        history.append({"role": "tool", "content": result})
    return {"status": "gave_up", "answer": "", "steps": MAX_STEPS}
'''
FAKES = '''"""A scripted stand-in for the language model, so everything runs offline."""


class ScriptedModel:
    """Replays a list of actions, then repeats the last one (a model that is stuck).

    Raises if asked more than 50 times, so a runaway loop ends in a test instead of hanging."""

    def __init__(self, actions):
        self.actions = actions
        self.calls = 0

    def __call__(self, history):
        self.calls += 1
        if self.calls > 50:
            raise RuntimeError("the model was called more than 50 times")
        return self.actions[min(self.calls, len(self.actions)) - 1]
'''
REPORT = '''import json

from src.agent import run
from src.fakes import ScriptedModel


def summary(path="data/scenarios.json"):
    """The numbers the nightly report shows."""
    scenarios = json.load(open(path))
    results = []
    for scenario in scenarios:
        try:
            results.append(run(ScriptedModel(scenario["actions"]), scenario["goal"]))
        except RuntimeError:
            continue  # the scheduler logs crashed runs
    done = sum(1 for r in results if r["status"] == "done")
    rate = round(done / len(results), 3) if results else 0.0
    return {"runs": len(results), "success_rate": rate}


if __name__ == "__main__":
    print(summary())
'''
README = """# Booking agent

`src/agent.py` runs a travel-booking agent: a model chooses tools (`src/tools.py`), the agent
runs them and loops until the model gives a final answer. `src/fakes.py` is a scripted stand-in
for the model. `data/scenarios.json` holds 30 recorded situations with the status each should end
in; `python -m src.report` prints the numbers on the nightly report.

Run the tests with `python -m pytest`.
"""
TESTS = """import json

from src.agent import MAX_STEPS, run
from src.fakes import ScriptedModel
from src.report import summary


def search(origin, dest):
    return {"type": "tool", "tool": "search_flights", "args": {"origin": origin, "dest": dest}}


def final(text):
    return {"type": "final", "text": text}


def test_a_good_run_finishes():
    model = ScriptedModel([search("LON", "PAR"), final("Found EZY802")])
    result = run(model, "a flight to Paris")
    assert result["status"] == "done" and result["steps"] == 2


def test_a_stuck_agent_stops_at_the_step_limit():
    model = ScriptedModel([search("LON", "MARS")])
    result = run(model, "a flight to Mars")
    assert model.calls <= MAX_STEPS
    assert result["status"] == "gave_up"


def test_a_failed_tool_is_not_reported_as_success():
    model = ScriptedModel([search("LON", "MARS"), final("All booked!")])
    assert run(model, "a flight to Mars")["status"] == "failed"


def test_an_error_the_agent_recovers_from_is_fine():
    model = ScriptedModel([search("LON", "MARS"), search("LON", "PAR"), final("Found it")])
    assert run(model, "somewhere")["status"] == "done"


def test_the_report_matches_a_hand_count_on_the_real_scenarios():
    scenarios = json.load(open("data/scenarios.json"))
    done = sum(1 for s in scenarios if s["expected"] == "done")
    assert summary()["runs"] == len(scenarios)
    assert summary()["success_rate"] == round(done / len(scenarios), 3)
"""
SCENARIO = (
    "Harbor Travel runs an AI agent that searches flights and books them for customers. The "
    "nightly report says the agent succeeds on every run it finishes, but customer operations "
    "keeps hearing from people told 'all booked' who have no booking, and last week one night "
    "of runs cost far more than usual. Your first week is about finding out what the agent is "
    "really doing."
)
CONTEXT = (
    "Harbor Travel has about 80 staff and a four-person AI team. The agent handles routine "
    "bookings end to end, so a wrong 'done' means a customer who thinks they are booked."
)


def _search(origin: str, dest: str) -> dict[str, object]:
    return {"type": "tool", "tool": "search_flights", "args": {"origin": origin, "dest": dest}}


def _book(flight: str) -> dict[str, object]:
    return {"type": "tool", "tool": "book", "args": {"flight": flight}}


def _final(text: str) -> dict[str, object]:
    return {"type": "final", "text": text}


def scenarios() -> list[dict[str, object]]:
    rng = random.Random(SEED)
    kinds = KINDS[:]
    rng.shuffle(kinds)
    valid = [("LON", "NYC"), ("LON", "PAR"), ("PAR", "ROM")]
    invalid = [("LON", "MARS"), ("ROM", "LIMA"), ("NYC", "OSLO"), ("PAR", "TOKYO")]
    out: list[dict[str, object]] = []
    for i, kind in enumerate(kinds, 1):
        good, bad = rng.choice(valid), rng.choice(invalid)
        if kind == "good":
            actions = [_search(*good), _book("EZY802"), _final("Booked for you.")]
            expected = "done"
        elif kind == "recovered":
            actions = [_search(*bad), _search(*good), _final("Found an alternative.")]
            expected = "done"
        elif kind == "failed":
            actions = [_search(*bad), _final("All booked, enjoy your trip!")]
            expected = "failed"
        else:
            actions = [_search(*bad)]
            expected = "gave_up"
        out.append({"id": i, "goal": f"booking request {i}", "actions": actions,
                    "expected": expected})  # fmt: skip
    return out


def truth() -> float:
    rows = scenarios()
    return sum(1 for r in rows if r["expected"] == "done") / len(rows)


def starter_reading() -> float:
    """What the buggy report shows: swallowed errors count as done, crashed runs vanish."""
    kept = [r for r in scenarios() if r["expected"] != "gave_up"]
    return sum(1 for _ in kept) / len(kept)


def files() -> tuple[dict[str, str], dict[str, str]]:
    shared = {
        "README.md": README,
        "src/__init__.py": "",
        "src/fakes.py": FAKES,
        "src/report.py": REPORT,
        "tests/test_agent.py": TESTS,
        "data/scenarios.json": json.dumps(scenarios(), indent=0),
    }
    starter = {**shared, "src/tools.py": TOOLS_BUGGY, "src/agent.py": AGENT_BUGGY}
    reference = {**shared, "src/tools.py": TOOLS_FIXED, "src/agent.py": AGENT_FIXED}
    return starter, reference


def tickets() -> list[Ticket]:
    return [
        Ticket(
            key="HT-101",
            title="The nightly report is all green. Is it?",
            description=(
                "Customer operations keeps meeting people told 'all booked' with no booking, yet "
                "the report says every finished run succeeded. Work out how the agent decides a "
                "run is done and make a failed tool call show up as a failure."
            ),
            acceptance_criteria=[
                "A run whose last tool call failed does not end as done",
                "A run that recovers from an earlier error still counts as done",
            ],
            task_type="code",
            due_day=1,
            skills=["ai-agents", "tool-calling"],
        ),
        Ticket(
            key="HT-102",
            title="One night of runs cost far more than usual",
            description=(
                "Some runs never seem to end. Make the agent stop when it is stuck, say so "
                "honestly, and make the nightly report match a hand count of the recorded "
                "scenarios."
            ),
            acceptance_criteria=[
                "The agent makes at most MAX_STEPS model calls and ends as gave_up",
                "The report number equals a hand count on data/scenarios.json",
            ],
            task_type="code",
            due_day=2,
            skills=["ai-agents", "llm-evaluation"],
        ),
        Ticket(
            key="HT-103",
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
            skills=["testing", "ai-agents"],
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
        crit("ai-agents", 0.30,
             _anchors("Trusts the report without watching a run.",
                      "Fixes one of the two causes and explains it.",
                      "Fixes both causes and explains how the loop decides to stop."),
             ["tests/test_agent.py passes"]),
        crit("tool-calling", 0.20,
             _anchors("Leaves tool errors invisible.", "Reports errors but loses recovery.",
                      "Reports errors to the model and still allows recovery."),
             ["a failed tool is not reported as success"]),
        crit("llm-evaluation", 0.25,
             _anchors("Accepts the green number.", "Fixes the number without checking it.",
                      "Checks the number by hand and explains the gap."),
             ["report equals the hand count"]),
        crit("testing", 0.25,
             _anchors("No new test.", "A test that passes before and after the fix.",
                      "A focused test that fails on the old code and passes on the fix."),
             ["new test fails on the starter", "new test passes on the reference"]),
    ]  # fmt: skip


PLANTED = [
    "tools.call swallows every exception and returns an empty string, so failed tools look fine",
    "agent.run ignores MAX_STEPS, so a stuck model loops, and always reports status done",
    "report.summary drops runs that crash, hiding the stuck ones from the success rate",
]


def metrics() -> dict[str, float]:
    return {"success_rate": round(truth(), 3), "dashboard_claims": round(starter_reading(), 3)}


def internship() -> Internship:
    colleagues = [
        Colleague(
            key="priya",
            name="Priya Nair",
            role="Head of Product",
            persona=(
                "Warm, quick, commercial. Cares whether customers can rely on the agent and what "
                "last week's bill means. Asks 'what do we know, and how sure are we?'. Does not "
                "read code."
            ),
        ),
        Colleague(
            key="tom",
            name="Tom Eriksen",
            role="Staff Engineer",
            persona=(
                "Calm and exact. Reviews carefully, likes small changes and tests that fail for "
                "the right reason. Answers with a hint or a question, never the fix."
            ),
        ),
        Colleague(
            key="lena",
            name="Lena Brandt",
            role="Customer Operations Lead",
            persona=(
                "Not technical. Talks about real customers: people told they are booked who are "
                "not. Frustrated that the report says all is well. Gives examples, not causes."
            ),
        ),
    ]
    events = [
        InternshipEvent(
            day=1, kind="message", sender="priya",
            text=(
                "Welcome to Harbor Travel! The one thing on my mind this week: our booking "
                "agent's nightly report says every run it finishes succeeds, and Lena's team "
                "does not believe it. Tom is your point of contact for the code. Say hi to both."
            ),
        ),
        InternshipEvent(
            day=1, kind="ticket", sender="priya", ticket="HT-101",
            text="HT-101 is on your board. Start there, and shout if anything is unclear.",
        ),
        InternshipEvent(
            day=2, kind="message", sender="lena",
            text=(
                "Hi, Lena from customer ops. Four customers this week were told 'all booked' and "
                "had nothing. Also finance asked me why one night's usage was so high. Could "
                "those be connected?"
            ),
        ),
        InternshipEvent(
            day=2, kind="ticket", sender="priya", ticket="HT-102",
            text="Lena's point deserves its own ticket: HT-102 is yours.",
        ),
        InternshipEvent(
            day=3, kind="message", sender="tom",
            text=(
                "Good progress. Before HT-103: tests are how this stays fixed. Keep the change "
                "small enough that I can review it over coffee."
            ),
        ),
        InternshipEvent(day=3, kind="ticket", sender="tom", ticket="HT-103",
                        text="HT-103 is on your board."),
        InternshipEvent(
            day=4, kind="message", sender="priya",
            text=(
                "I present to the leadership team tomorrow. In a few plain sentences, can you "
                "write to me: can we trust the agent's report, what was wrong, and how sure are "
                "you? Send it as a message in this chat."
            ),
        ),
        InternshipEvent(
            day=5, kind="meeting", sender="priya",
            text=(
                "Friday retro: what went well, what you would do differently, and what you still "
                "do not know. Then I will write up how the week went."
            ),
        ),
    ]  # fmt: skip
    return Internship(colleagues=colleagues, events=events)
