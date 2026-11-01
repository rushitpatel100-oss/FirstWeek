"""Skill gap: the model's judgement is kept only where the person's own words back it."""

import json
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from test_passages import db_fixture
from test_report import ROLE, _no_versions
from test_review import store

from firstweek_core.config import Settings
from firstweek_core.contracts import GapDraftItem, GapReply, SkillStat
from firstweek_core.llm import BudgetRegistry, LLMGateway
from firstweek_core.llm.tracing import NoopTracer
from firstweek_research import gap

BACKGROUND = (
    "I was a mechanical engineer for six years. I write Python scripts to analyse test data."
)


def skill(skill_id: str, label: str, share: float) -> SkillStat:
    return SkillStat(
        skill_id=skill_id,
        label=label,
        count=int(share * 20),
        share=share,
        ci_low=max(0.0, share - 0.2),
        ci_high=min(1.0, share + 0.2),
        n=20,
    )


SKILLS = [skill("python", "Python", 0.8), skill("rag", "RAG", 0.4), skill("k8s", "Kubernetes", 0.2)]


def draft(skill_id: str, status: str, quote: str | None, reason: str = "Because.") -> GapDraftItem:
    return GapDraftItem(
        skill_id=skill_id,
        status=status,
        background_quote=quote,
        reason=reason,
    )


def test_a_claim_needs_words_that_are_really_in_the_background() -> None:
    items = gap.check_items(
        [
            draft("python", "have", "I write Python scripts", "States it plainly."),
            draft("rag", "transferable", "I have built search engines", "Close."),  # invented
            draft("k8s", "missing", None, "A container orchestrator."),
        ],
        SKILLS,
        BACKGROUND,
    )
    assert [(i.skill_id, i.status) for i in items] == [
        ("python", "have"),
        ("rag", "missing"),
        ("k8s", "missing"),
    ]
    assert 'you wrote: "I write Python scripts"' in items[0].reason
    assert items[1].reason == "Nothing in your background says this."


def test_unknown_skills_are_ignored_repeats_use_the_first_and_skipped_skills_are_missing() -> None:
    items = gap.check_items(
        [
            draft("python", "have", "write Python scripts"),
            draft("python", "missing", None),
            draft("made-up", "have", "mechanical engineer"),
        ],
        SKILLS,
        BACKGROUND,
    )
    assert [i.skill_id for i in items] == ["python", "rag", "k8s"]
    assert items[0].status == "have"
    assert [i.reason for i in items[1:]] == ["Not assessed.", "Not assessed."]


def test_coverage_is_weighted_by_how_often_postings_ask_and_a_close_match_counts_half() -> None:
    items = gap.check_items(
        [
            draft("python", "have", "write Python scripts"),
            draft("rag", "transferable", "analyse test data"),
        ],
        SKILLS,
        BACKGROUND,
    )
    result = gap.SkillGap(
        items=items,
        shares={s.skill_id: s.share for s in SKILLS},
        labels={s.skill_id: s.label for s in SKILLS},
        model="m",
        cost_usd=0.0,
    )
    assert result.coverage == pytest.approx((0.8 + 0.5 * 0.4) / 1.4)
    text = gap.to_text(result, "GenAI Engineer")
    assert "## You have (1)" in text and "## Missing (1)" in text and "71%" in text


async def _completion(**kwargs: Any) -> SimpleNamespace:
    user = kwargs["messages"][-1]["content"]
    assert BACKGROUND in user and "- python | Python | 80%" in user
    reply = GapReply(items=[draft("python", "have", "write Python scripts")])
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=reply.model_dump_json()))],
        usage=SimpleNamespace(prompt_tokens=900, completion_tokens=200),
    )


def gateway() -> LLMGateway:
    return LLMGateway(
        settings=Settings(_env_file=None),
        completion_fn=_completion,
        tracer=NoopTracer(),
        budgets=BudgetRegistry(Decimal("5")),
    )


async def test_the_background_and_skills_reach_the_model_and_the_reply_is_checked() -> None:
    result = await gap.skill_gap(gateway(), "GenAI Engineer", SKILLS, BACKGROUND)
    assert [i.status for i in result.items] == ["have", "missing", "missing"]
    assert json.dumps(GapReply.model_json_schema())


async def test_an_empty_background_or_no_skills_is_a_clear_error() -> None:
    with pytest.raises(gap.GapError, match="background"):
        await gap.skill_gap(gateway(), "GenAI Engineer", SKILLS, "   ")
    with pytest.raises(gap.GapError, match="no skills"):
        await gap.skill_gap(gateway(), "GenAI Engineer", [], BACKGROUND)


@pytest.mark.db
@pytest.mark.usefixtures("_db", "_no_versions")
def test_the_skills_come_from_the_newest_stored_report_and_below_20_percent_are_left_out() -> None:
    from sqlalchemy import select

    from firstweek_core.db.models import RoleReport
    from firstweek_core.db.session import session_scope

    low = skill("react", "React", 0.13)
    report_id = store(1)
    with session_scope() as session:
        row = session.execute(select(RoleReport).where(RoleReport.id == report_id)).scalar_one()
        row.report = {
            **row.report,
            "asked_for": [
                s.model_dump(mode="json")
                for s in (skill("rag", "RAG", 0.4), skill("python", "Python", 0.8), low)
            ],
        }
    assert [s.skill_id for s in gap.asked_skills(slug=ROLE)] == ["python", "rag"]
    assert [s.skill_id for s in gap.asked_skills(report_id)] == ["python", "rag"]
    with pytest.raises(gap.GapError, match="make report"):
        gap.asked_skills(slug="no-such-role")


__all__ = ["_no_versions", "db_fixture"]  # registers the fixtures here
