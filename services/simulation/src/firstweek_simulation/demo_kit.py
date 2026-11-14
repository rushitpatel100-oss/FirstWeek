"""Shared pieces for the hand-written practice projects (ADR 0029).

Each role's module keeps what is specific to it (code, data, story, numbers). The ticket, rubric
and five-day-week shapes are the same everywhere, so they are built here from short specs."""

from dataclasses import dataclass

from firstweek_core.contracts import (
    Colleague,
    Criterion,
    Internship,
    InternshipEvent,
    Ticket,
)

LEVELS = "Partly there, with gaps."
SOLID = "Solid, with one small gap."


@dataclass(frozen=True)
class TicketSpec:
    title: str
    description: str
    criteria: tuple[str, str]
    skills: tuple[str, ...]


@dataclass(frozen=True)
class CriterionSpec:
    skill: str
    weight: float
    low: str
    mid: str
    high: str
    checks: tuple[str, ...]


@dataclass(frozen=True)
class Person:
    key: str
    name: str
    role: str
    persona: str


REGRESSION = TicketSpec(
    "Make sure this cannot quietly come back",
    "Add a regression test of your own in a new file under tests/ that fails on the original "
    "code and passes on your fix, and keep your changes small enough for someone else to review "
    "quickly.",
    ("A new test fails on the original code and passes on the fix", "Existing tests still pass"),
    ("testing",),
)
REGRESSION_CRITERION_ANCHORS = (
    "No new test.",
    "A test that passes before and after the fix.",
    "A focused test that fails on the old code and passes on the fix.",
)


def tickets(prefix: str, specs: list[TicketSpec]) -> list[Ticket]:
    """Tickets PREFIX-101, 102, 103... due on days 1, 2, 3."""
    return [
        Ticket(
            key=f"{prefix}-{101 + i}",
            title=s.title,
            description=s.description,
            acceptance_criteria=list(s.criteria),
            task_type="code",
            due_day=i + 1,
            skills=list(s.skills),
        )
        for i, s in enumerate(specs)
    ]


def rubric(specs: list[CriterionSpec]) -> list[Criterion]:
    return [
        Criterion(
            skill_id=s.skill,
            weight=s.weight,
            anchors=dict(enumerate([s.low, LEVELS, s.mid, SOLID, s.high], 1)),
            checks=list(s.checks),
        )
        for s in specs
    ]


def testing_criterion(weight: float = 0.25) -> CriterionSpec:
    low, mid, high = REGRESSION_CRITERION_ANCHORS
    return CriterionSpec(
        "testing", weight, low, mid, high,
        ("new test fails on the starter", "new test passes on the reference"),
    )  # fmt: skip


def week(
    people: list[Person],
    keys: list[str],
    *,
    welcome: str,
    stakeholder: str,
    nudge: str,
    summary: str,
    retro: str,
) -> Internship:
    """The standard week. people[0] runs it, people[1] reviews code, people[2] is the
    non-technical stakeholder. `keys` are the three ticket keys in order."""
    lead, reviewer, outsider = people[0].key, people[1].key, people[2].key
    events = [
        InternshipEvent(day=1, kind="message", sender=lead, text=welcome),
        InternshipEvent(
            day=1, kind="ticket", sender=lead, ticket=keys[0],
            text=f"{keys[0]} is on your board. Start there, and shout if anything is unclear.",
        ),
        InternshipEvent(day=2, kind="message", sender=outsider, text=stakeholder),
        InternshipEvent(
            day=2, kind="ticket", sender=lead, ticket=keys[1],
            text=f"That deserves its own ticket: {keys[1]} is yours.",
        ),
        InternshipEvent(day=3, kind="message", sender=reviewer, text=nudge),
        InternshipEvent(
            day=3, kind="ticket", sender=reviewer, ticket=keys[2],
            text=f"{keys[2]} is on your board.",
        ),
        InternshipEvent(day=4, kind="message", sender=lead, text=summary),
        InternshipEvent(day=5, kind="meeting", sender=lead, text=retro),
    ]  # fmt: skip
    colleagues = [Colleague(key=p.key, name=p.name, role=p.role, persona=p.persona) for p in people]
    return Internship(colleagues=colleagues, events=events)


REVIEWER_PERSONA = (
    "Precise and kind. Reviews carefully, likes small changes and tests that fail for the right "
    "reason. Answers with a hint or a question, never the fix."
)
NUDGE = (
    "Good progress. Before the next ticket: tests are how this stays fixed. Keep the change "
    "small enough that I can review it over coffee."
)
RETRO = (
    "Friday retro: what went well, what you would do differently, and what you still do not "
    "know. Then I will write up how the week went."
)
