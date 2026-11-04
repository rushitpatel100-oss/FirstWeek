"""Blueprint design: the model proposes, code checks (ADR 0018)."""

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, select, text
from sqlalchemy.exc import OperationalError

from firstweek_core.contracts import (
    ArchetypeStats,
    BlueprintDraft,
    Citation,
    Claim,
    CriterionDraft,
    ProjectBlueprint,
    RoleRealityReport,
    SkillStat,
    TicketDraft,
)
from firstweek_core.db.models import ArchetypeVersion, Blueprint, RoleReport
from firstweek_core.db.session import get_engine, session_scope
from firstweek_research.roles import load_roles
from firstweek_research.stats import save_version
from firstweek_research.store import seed_roles
from firstweek_simulation import blueprint as bp

ROLE = "genai-engineer"


def skill(skill_id: str, share: float) -> SkillStat:
    return SkillStat(
        skill_id=skill_id,
        label=skill_id.title(),
        count=int(share * 20),
        share=share,
        ci_low=0.0,
        ci_high=1.0,
        n=20,
    )


FINDINGS = bp.Findings(
    version_id=uuid.uuid4(),
    role_name="GenAI Engineer",
    pain_points=["Retrieval cites outdated documents.", "Evaluation sets go stale."],
    responsibilities=["Build retrieval pipelines."],
    skills=[skill("python", 0.8), skill("rag", 0.5), skill("evals", 0.3)],
)
LIBRARY = bp.load_task_library()
ALLOWED = LIBRARY.allowed(ROLE)
ANCHORS = [f"Level {i} work looks like this." for i in range(1, 6)]


def ticket(
    title: str, task_type: str = "code", day: int = 1, skills: list[str] | None = None
) -> Any:
    return TicketDraft(
        title=title,
        description="Do the thing described here, carefully and fully.",
        acceptance_criteria=["It works.", "It is tested."],
        task_type=task_type,
        due_day=day,
        skills=skills or ["python"],
    )


def criterion(skill_id: str, weight: float = 1.0) -> CriterionDraft:
    return CriterionDraft(
        skill_id=skill_id, weight=weight, anchors=ANCHORS, checks=["pytest passes"]
    )


def good_draft(**changes: Any) -> BlueprintDraft:
    fields: dict[str, Any] = {
        "company_name": "Lumen Legal",
        "company_context": "Lumen Legal sells contract search to law firms. " * 2,
        "scenario": "The search assistant cites superseded clauses and the lead wants it fixed. "
        * 2,
        "grounded_in": [1],
        "tickets": [
            ticket("Fix stale citations", "code", 1, ["python", "rag"]),
            ticket("Write the rollout design note", "design_doc", 3, ["evals"]),
            ticket("Reply to the partner", "message", 5, ["python"]),
        ],
        "rubric": [criterion("python", 3), criterion("rag", 2), criterion("evals", 1)],
        "planted_issues": [
            "Index never drops superseded documents.",
            "Eval set has leaked rows.",
            "Retriever ignores document dates.",
        ],
        "expected_metrics": {"citation_accuracy": 0.9},
    }
    fields.update(changes)
    return BlueprintDraft(**fields)


def issues(draft: BlueprintDraft) -> list[str]:
    return bp.problems_with(draft, FINDINGS, ALLOWED, LIBRARY)


def test_the_task_library_covers_every_role_and_each_engineering_role_can_set_code() -> None:
    for slug in load_roles():
        assert "code" in LIBRARY.allowed(slug)
    assert LIBRARY.allowed("some-new-role") == LIBRARY.default
    assert "design_doc" not in LIBRARY.checkable and "code" in LIBRARY.checkable


def test_a_sound_draft_has_no_problems() -> None:
    assert issues(good_draft()) == []


@pytest.mark.parametrize(
    ("changes", "fragment"),
    [
        ({"grounded_in": [3]}, "pain point numbers"),
        ({"grounded_in": [1, 1]}, "pain point numbers"),
        (
            {
                "tickets": [
                    ticket("a" * 6, "notebook"),
                    ticket("b" * 6, "code", 2),
                    ticket("c" * 6, "code", 3),
                ]
            },
            "",
        ),
        (
            {
                "tickets": [
                    ticket("Fix it up", "design_doc", 1),
                    ticket("Write it up", "message", 2),
                    ticket("Plan it out", "design_doc", 3),
                ]
            },
            "code ticket",
        ),
        (
            {
                "tickets": [
                    ticket("First job", "code", 1),
                    ticket("Second job", "code", 1),
                    ticket("Third job", "code", 2),
                ]
            },
            "different days",
        ),
        (
            {
                "tickets": [
                    ticket("First job", "code", 1, ["made_up"]),
                    ticket("Second job", "code", 2),
                    ticket("Third job", "code", 3),
                ]
            },
            "unknown skills",
        ),
        (
            {"rubric": [criterion("python"), criterion("python"), criterion("rag")]},
            "once in the rubric",
        ),
        (
            {"rubric": [criterion("python"), criterion("rag"), criterion("nonsense")]},
            "unknown skills",
        ),
        (
            {
                "rubric": [
                    criterion("python"),
                    criterion("rag"),
                    criterion("evals"),
                    criterion("sql"),
                ]
            },
            "unknown",
        ),
    ],
)
def test_each_kind_of_flaw_is_reported(changes: dict[str, Any], fragment: str) -> None:
    found = issues(good_draft(**changes))
    assert found and any(fragment in p for p in found)


def test_skills_a_ticket_assesses_must_be_in_the_rubric_and_the_reverse() -> None:
    missing = issues(
        good_draft(
            rubric=[criterion("python"), criterion("rag"), criterion("evals")],
            tickets=[
                ticket("First job", "code", 1, ["python"]),
                ticket("Second job", "code", 2, ["python"]),
                ticket("Third job", "code", 3, ["python"]),
            ],
        )
    )
    assert any("no ticket assesses" in p for p in missing)
    short = issues(good_draft(rubric=[criterion("python"), criterion("rag"), criterion("python")]))
    assert short


def test_five_different_concrete_anchors_are_required() -> None:
    same = CriterionDraft(
        skill_id="python", weight=1, anchors=["Same words here."] * 5, checks=["t"]
    )
    draft = good_draft(rubric=[same, criterion("rag"), criterion("evals")])
    assert any("five different" in p for p in issues(draft))
    with pytest.raises(ValidationError):
        CriterionDraft(skill_id="python", weight=1, anchors=["Only one anchor."], checks=["t"])
    built = bp.build_blueprint(good_draft(), FINDINGS)
    assert set(built.rubric[0].anchors) == {1, 2, 3, 4, 5}


def test_weights_scale_to_one() -> None:
    for weights in ([3, 2, 1], [1, 1, 1], [10, 1, 1, 1, 1], [0.001, 5, 5]):
        scaled = bp.scale_weights([float(w) for w in weights])
        assert abs(sum(scaled) - 1.0) < 1e-9 and min(scaled) >= bp.MIN_WEIGHT - 0.01


def test_a_checked_draft_becomes_a_valid_blueprint_without_leaking_the_key() -> None:
    blueprint = bp.build_blueprint(good_draft(), FINDINGS)
    ProjectBlueprint.model_validate(blueprint.model_dump())
    assert [t.key for t in blueprint.tickets] == ["GENAI-101", "GENAI-102", "GENAI-103"]
    assert [t.due_day for t in blueprint.tickets] == [1, 3, 5]
    assert blueprint.scenario.startswith("Lumen Legal: ")
    assert blueprint.answer_key.reference_solution_uri == bp.PENDING_SOLUTION
    assert "answer_key" not in blueprint.public_view()
    assert "leaked rows" not in str(blueprint.public_view())


def test_ticket_prefixes() -> None:
    assert bp.ticket_prefix("GenAI Engineer") == "GENAI"
    assert bp.ticket_prefix("Agentic AI Engineer") == "AGENTIC"
    assert bp.ticket_prefix("AI Software Engineer") == "AI"
    assert bp.ticket_prefix("3D Artist") == "SIM"


class FakeGateway:
    def __init__(self, *drafts: BlueprintDraft) -> None:
        self.drafts, self.calls = list(drafts), []  # type: ignore[var-annotated]

    async def structured(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(parsed=self.drafts.pop(0), cost_usd=Decimal("0.10"), model="fake")


async def test_the_findings_reach_the_model_and_a_good_design_is_kept() -> None:
    gateway = FakeGateway(good_draft())
    designed = await bp.design_blueprint(gateway, ROLE, FINDINGS)  # type: ignore[arg-type]
    user = gateway.calls[0]["messages"][1]["content"]
    assert "1. Retrieval cites outdated documents." in user and "python | Python | 80%" in user
    assert "- code:" in user and "notebook" in user and "prioritisation" not in user
    assert designed.attempts == 1 and designed.grounded_in == [
        "Retrieval cites outdated documents."
    ]
    assert designed.cost_usd == pytest.approx(0.10)


async def test_one_repair_attempt_gets_the_problems_and_a_second_failure_is_reported() -> None:
    gateway = FakeGateway(good_draft(grounded_in=[7]), good_draft())
    designed = await bp.design_blueprint(gateway, ROLE, FINDINGS)  # type: ignore[arg-type]
    assert designed.attempts == 2 and designed.cost_usd == pytest.approx(0.20)
    assert "pain point numbers" in gateway.calls[1]["messages"][1]["content"]
    with pytest.raises(bp.BlueprintError, match="pain point numbers"):
        await bp.design_blueprint(
            FakeGateway(*[good_draft(grounded_in=[7])] * 3),  # type: ignore[arg-type]
            ROLE,
            FINDINGS,
        )


def test_auto_repair_fixes_skill_mismatches_without_a_model_call() -> None:
    draft = good_draft(
        tickets=[
            ticket("Fix stale citations", "code", 1, ["python", "rag", "tracing"]),
            ticket("Write the rollout design note", "design_doc", 3, ["evals"]),
            ticket("Reply to the partner", "message", 5, ["python"]),
        ],
        rubric=[criterion("python", 3), criterion("rag", 2), criterion("evals", 1)],
    )
    assert any("missing from the rubric" in p for p in issues(draft))
    fixed = bp.auto_repair(draft)
    assert issues(fixed) == [] and fixed.tickets[0].skills == ["python", "rag"]
    unused = good_draft(rubric=[*good_draft().rubric, criterion("tracing")])
    assert any("no ticket assesses" in p for p in issues(unused))
    assert issues(bp.auto_repair(unused)) == []
    only = good_draft(tickets=[ticket("Only one job", "code", 1, ["tracing"])] * 3)
    assert bp.auto_repair(only).tickets[0].skills == ["tracing"]  # never left with none


async def test_a_skill_mismatch_is_repaired_by_code_and_costs_one_call() -> None:
    bad = good_draft(
        tickets=[
            ticket("Fix stale citations", "code", 1, ["python", "rag", "tracing"]),
            ticket("Write the rollout design note", "design_doc", 3, ["evals"]),
            ticket("Reply to the partner", "message", 5, ["python"]),
        ]
    )
    gateway = FakeGateway(bad)
    designed = await bp.design_blueprint(gateway, ROLE, FINDINGS)  # type: ignore[arg-type]
    assert designed.attempts == 1 and len(gateway.calls) == 1


def test_the_text_for_a_reviewer_shows_the_answer_key() -> None:
    designed = bp.DesignedBlueprint(
        bp.build_blueprint(good_draft(), FINDINGS), ["pain"], 1, "m", 0.1
    )
    out = bp.to_text(designed)
    assert "GENAI-101" in out and "Answer key" in out and "leaked rows" in out


@pytest.fixture
def _db() -> None:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError:
        pytest.skip("No database available")
    with session_scope() as session:
        session.execute(delete(Blueprint))
        session.execute(delete(ArchetypeVersion))


def claim(text_: str) -> Claim:
    return Claim(
        text=text_,
        citations=[Citation(source_url="https://blog.example.com/x", tier="blog", quote="a quote")],
        confidence=0.5,
        verification="supported",
    )


def stored_report(pain_points: list[Claim], asked_for: list[SkillStat]) -> uuid.UUID:
    with session_scope() as session:
        archetype_id = seed_roles(session, load_roles())[ROLE]
        version = save_version(
            session,
            archetype_id,
            ArchetypeStats(
                role="GenAI Engineer",
                country="GB",
                sample_size=20,
                employers=14,
                date_range=(date(2026, 5, 4), date(2026, 10, 28)),
                sources={"greenhouse": 20},
                skills=asked_for,
                tools=[],
                seniority={"senior": 12, "mid": 8},
                salary=[],
                demand_snippets=0,
                unverified_items_dropped=0,
                unmapped_terms=0,
                classifier_version="classify-role.v1",
                extractor_version="extract-posting.v1",
            ),
        )
        assert version is not None
        report = RoleRealityReport(
            archetype="GenAI Engineer",
            trust_level="golden",
            version=1,
            country="GB",
            sample_size=20,
            date_range=(date(2026, 5, 4), date(2026, 10, 28)),
            summary=[],
            asked_for=asked_for,
            responsibilities=[claim("Builds retrieval pipelines.")],
            day_to_day=[],
            typical_week=[],
            pain_points=pain_points,
        )
        session.add(
            RoleReport(archetype_version_id=version.id, report=report.model_dump(mode="json"))
        )
        return version.id


@pytest.mark.db
@pytest.mark.usefixtures("_db")
def test_findings_come_from_the_stored_report_and_a_draft_blueprint_is_saved() -> None:
    with pytest.raises(bp.BlueprintError, match="make report"):
        bp.load_findings(ROLE)
    version_id = stored_report(
        [claim("Retrieval cites old documents.")], [skill("python", 0.8), skill("rare", 0.05)]
    )
    findings = bp.load_findings(ROLE)
    assert findings.version_id == version_id and findings.role_name == "GenAI Engineer"
    assert findings.pain_points == ["Retrieval cites old documents."]
    assert [s.skill_id for s in findings.skills] == ["python"]  # 5% is not worth assessing
    assert findings.responsibilities == ["Builds retrieval pipelines."]

    designed = bp.DesignedBlueprint(bp.build_blueprint(good_draft(), findings), ["x"], 1, "m", 0.1)
    blueprint_id = bp.store_blueprint(findings, designed)
    with session_scope() as session:
        row = session.execute(select(Blueprint).where(Blueprint.id == blueprint_id)).scalar_one()
        assert row.status == "draft" and row.validated is False
        assert "answer_key" not in row.blueprint
        assert row.answer_key["planted_issues"][0].startswith("Index never drops")


@pytest.mark.db
@pytest.mark.usefixtures("_db")
def test_a_report_without_pain_points_or_skills_is_a_clear_error() -> None:
    stored_report([], [skill("python", 0.8)])
    with pytest.raises(bp.BlueprintError, match="pain points"):
        bp.load_findings(ROLE)
