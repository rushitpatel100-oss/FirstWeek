"""Writing the scripted week for a generated project (ADR 0023).

The writer sees the public blueprint only, like every colleague agent, so it cannot leak the
answer key. Code checks the script against the project: every ticket is assigned once, on time,
by a colleague who exists, and no message points at code."""

import json
import re
from dataclasses import dataclass

from firstweek_core.contracts import Internship, ProjectBlueprint
from firstweek_core.llm import LLMGateway
from firstweek_core.llm import Tier as ModelTier
from firstweek_simulation.blueprint import BlueprintError, load_prompt

WEEK_VERSION = "design-week.v1"
MAX_TRIES = 3
MIN_DAYS = 4
CODE_HINT = re.compile(r"`|\.py\b|\.json\b|\bdef \w+\(|\w+\(\)")
TICKET_KEY = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")


@dataclass
class DesignedWeek:
    script: Internship
    cost_usd: float


def problems(script: Internship, blueprint: ProjectBlueprint) -> list[str]:
    """What is wrong with the script as a week for this project; empty when it is fine."""
    found: list[str] = []
    people = [c.key for c in script.colleagues]
    if len(set(people)) != len(people):
        found.append("colleague keys must be unique")
    if len(people) < 2:
        found.append("write at least two colleagues")
    due = {t.key: t.due_day for t in blueprint.tickets}
    assigned: dict[str, int] = {}
    for event in script.events:
        if event.sender not in people:
            found.append(f"day {event.day}: sender {event.sender!r} is not a colleague")
        if event.ticket is not None:
            if event.ticket not in due:
                found.append(f"day {event.day}: unknown ticket {event.ticket}")
            else:
                assigned[event.ticket] = assigned.get(event.ticket, 0) + 1
                if event.day > due[event.ticket]:
                    found.append(
                        f"{event.ticket} is assigned after its due day {due[event.ticket]}"
                    )
            if event.kind != "ticket":
                found.append(f"day {event.day}: an event that assigns a ticket must be a ticket")
        elif event.kind == "ticket":
            found.append(f"day {event.day}: a ticket event must name its ticket")
        if CODE_HINT.search(event.text):
            found.append(f"day {event.day}: the message mentions code; say what people noticed")
        for key in TICKET_KEY.findall(event.text):
            if key not in due:
                found.append(f"day {event.day}: mentions {key}, which is not a ticket")
    for key in due:
        if assigned.get(key, 0) != 1:
            found.append(f"{key} must be assigned exactly once, not {assigned.get(key, 0)} times")
    if len({e.day for e in script.events}) < MIN_DAYS:
        found.append(f"events must fall on at least {MIN_DAYS} different days")
    if not any(e.day >= 4 for e in script.events):
        found.append("day 4 or 5 needs a request to explain the findings in plain words")
    return found


def _tickets_text(blueprint: ProjectBlueprint) -> str:
    return "\n".join(
        f"- {t.key} (due day {t.due_day}): {t.title}. {t.description}" for t in blueprint.tickets
    )


async def design_week(
    gateway: LLMGateway,
    blueprint: ProjectBlueprint,
    *,
    tier: ModelTier = "judge",
    budget_usd: float = 0.5,
    tries: int = MAX_TRIES,
) -> DesignedWeek:
    """One validated week, or BlueprintError after `tries` attempts that code rejects."""
    public = blueprint.public_view()  # no answer key
    system, template = load_prompt(WEEK_VERSION)
    feedback = ""
    cost = 0.0
    last: list[str] = []
    for _ in range(tries):
        user = template.format(
            company=public["company_context"],
            scenario=public["scenario"],
            tickets=_tickets_text(blueprint),
            problems=feedback or "(none)",
        )
        result = await gateway.structured(
            purpose="design-week",
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_model=Internship,
            tier=tier,
            budget_scope=f"week:{blueprint.archetype}",
            budget_usd=budget_usd,
            max_tokens=4000,
            prompt_version=WEEK_VERSION,
        )
        cost += float(result.cost_usd)
        assert result.parsed is not None
        last = problems(result.parsed, blueprint)
        if not last:
            return DesignedWeek(result.parsed, cost)
        feedback = "\n".join(f"- {p}" for p in last)
    raise BlueprintError("The week never passed the checks:\n" + json.dumps(last, indent=2))
