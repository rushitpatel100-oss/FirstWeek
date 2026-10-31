from datetime import date

import pytest
from pydantic import ValidationError

from firstweek_core.contracts import (
    AnswerKey,
    Citation,
    Claim,
    Criterion,
    ProjectBlueprint,
    RoleRealityReport,
    SkillStat,
    Ticket,
)

ANCHORS = {1: "missing", 2: "weak", 3: "adequate", 4: "strong", 5: "exemplary"}


def _ticket(key: str = "GENAI-101", skills: list[str] | None = None) -> Ticket:
    return Ticket(
        key=key,
        title="Fix stale citations",
        description="The RAG bot cites outdated docs.",
        acceptance_criteria=["Answers cite docs updated in the last 90 days"],
        task_type="code",
        due_day=2,
        skills=skills or ["rag"],
    )


def _blueprint(**overrides: object) -> ProjectBlueprint:
    data: dict[str, object] = {
        "archetype": "genai-engineer",
        "scenario": "Support bot cites outdated docs",
        "company_context": "A fictional fintech",
        "tickets": [_ticket()],
        "rubric": [Criterion(skill_id="rag", weight=1.0, anchors=ANCHORS)],
        "answer_key": AnswerKey(reference_solution_uri="s3://ref", planted_issues=["off-by-one"]),
    }
    data.update(overrides)
    return ProjectBlueprint.model_validate(data)


def test_claim_needs_a_citation() -> None:
    with pytest.raises(ValidationError):
        Claim(text="Most roles use RAG", citations=[], confidence=0.8, verification="supported")


def test_claim_confidence_labels() -> None:
    cite = Citation(source_url="https://example.com/job", tier="posting", quote="RAG pipelines")
    labels = [
        Claim(text="x", citations=[cite], confidence=c, verification="supported").confidence_label
        for c in (0.9, 0.6, 0.2)
    ]
    assert labels == ["high", "medium", "low"]


def test_skill_stat_share_must_sit_inside_interval() -> None:
    SkillStat(skill_id="rag", label="RAG", share=0.6, ci_low=0.5, ci_high=0.7, n=120)
    with pytest.raises(ValidationError):
        SkillStat(skill_id="rag", label="RAG", share=0.9, ci_low=0.5, ci_high=0.7, n=120)


def test_report_dates_must_be_ordered() -> None:
    with pytest.raises(ValidationError):
        RoleRealityReport(
            archetype="genai-engineer",
            trust_level="golden",
            version=1,
            country="GB",
            sample_size=0,
            date_range=(date(2026, 10, 1), date(2026, 9, 1)),
            summary=[],
            asked_for=[],
            day_to_day=[],
            typical_week=[],
            pain_points=[],
        )


def test_ticket_key_format() -> None:
    with pytest.raises(ValidationError):
        _ticket(key="genai 101")


def test_criterion_needs_all_five_anchors() -> None:
    with pytest.raises(ValidationError):
        Criterion(skill_id="rag", weight=1.0, anchors={1: "a", 5: "e"})


def test_blueprint_rubric_weights_sum_to_one() -> None:
    with pytest.raises(ValidationError, match=r"sum to 1\.0"):
        _blueprint(rubric=[Criterion(skill_id="rag", weight=0.5, anchors=ANCHORS)])


def test_blueprint_tickets_only_assess_rubric_skills() -> None:
    with pytest.raises(ValidationError, match="missing from the rubric"):
        _blueprint(tickets=[_ticket(skills=["kubernetes"])])


def test_blueprint_public_view_hides_answer_key() -> None:
    view = _blueprint().public_view()
    assert "answer_key" not in view
    assert view["archetype"] == "genai-engineer"
