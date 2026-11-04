"""The generated week must fit the project and never point at code (ADR 0023)."""

import json
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from test_blueprint import FINDINGS, good_draft

from firstweek_core.config import Settings
from firstweek_core.contracts import Colleague, Internship, InternshipEvent, ProjectBlueprint
from firstweek_core.llm import BudgetRegistry, LLMGateway
from firstweek_core.llm.tracing import NoopTracer
from firstweek_simulation import blueprint as bp
from firstweek_simulation import week as wk


def project() -> ProjectBlueprint:
    return bp.build_blueprint(good_draft(), FINDINGS)


def script(blueprint: ProjectBlueprint) -> Internship:
    people = [
        Colleague(key="boss", name="Alex Hart", role="Manager", persona="Warm and busy."),
        Colleague(key="lead", name="Jo Park", role="Tech Lead", persona="Direct and kind."),
    ]
    events = [
        InternshipEvent(day=1, kind="message", sender="boss", text="Welcome! Glad you are here."),
        InternshipEvent(day=2, kind="message", sender="lead", text="Tests keep this honest."),
        InternshipEvent(day=4, kind="message", sender="boss", text="Tell me in plain words."),
        InternshipEvent(day=5, kind="meeting", sender="boss", text="Friday retro."),
    ]
    for t in blueprint.tickets:
        events.append(
            InternshipEvent(
                day=min(t.due_day, 3), kind="ticket", sender="boss", ticket=t.key, text="On you."
            )
        )
    return Internship(colleagues=people, events=events)


def test_a_week_that_fits_the_project_has_no_problems() -> None:
    blueprint = project()
    assert wk.problems(script(blueprint), blueprint) == []


def test_problems_name_what_is_wrong() -> None:
    blueprint = project()
    broken = script(blueprint)
    first = blueprint.tickets[0].key
    broken.events = [e for e in broken.events if e.ticket != first]  # never assigned
    broken.events.append(
        InternshipEvent(day=1, kind="message", sender="ghost", text="Look at `metrics.py` now.")
    )
    broken.events.append(InternshipEvent(day=2, kind="message", sender="boss", text="See ZZ-9."))
    text = "\n".join(wk.problems(broken, blueprint))
    assert f"{first} must be assigned exactly once" in text
    assert "'ghost' is not a colleague" in text and "mentions code" in text
    assert "ZZ-9, which is not a ticket" in text


class Replies:
    def __init__(self, contents: list[str]) -> None:
        self.contents = contents
        self.seen: list[str] = []

    async def __call__(self, **kwargs: Any) -> SimpleNamespace:
        self.seen.append(" ".join(str(m["content"]) for m in kwargs["messages"]))
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=self.contents.pop(0)), finish_reason="stop"
                )
            ],
            usage=SimpleNamespace(prompt_tokens=300, completion_tokens=100),
        )


def gateway(replies: Replies) -> LLMGateway:
    return LLMGateway(
        settings=Settings(_env_file=None), completion_fn=replies, tracer=NoopTracer(),
        budgets=BudgetRegistry(Decimal("5")), recorder=lambda _: None,
    )  # fmt: skip


async def test_a_rejected_week_is_retried_with_the_problems_and_never_sees_the_key() -> None:
    blueprint = project()
    good = script(blueprint)
    bad = good.model_copy(update={"events": good.events[:1]})
    replies = Replies([bad.model_dump_json(), good.model_dump_json()])
    designed = await wk.design_week(gateway(replies), blueprint, tries=2)
    assert designed.script == good
    assert "must be assigned exactly once" in replies.seen[1]
    secret = blueprint.answer_key.planted_issues[0]
    assert all(secret not in seen for seen in replies.seen)


async def test_a_week_that_never_passes_raises() -> None:
    blueprint = project()
    bad = json.dumps(
        script(blueprint).model_dump() | {"events": script(blueprint).model_dump()["events"][:1]}
    )
    with pytest.raises(bp.BlueprintError):
        await wk.design_week(gateway(Replies([bad, bad])), blueprint, tries=2)
