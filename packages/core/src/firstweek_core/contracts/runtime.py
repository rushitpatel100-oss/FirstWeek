"""Contracts for a running simulation: shared project state and evaluation results."""

from typing import Literal

from pydantic import BaseModel, Field

TicketStatus = Literal["todo", "in_progress", "in_review", "done"]


class Decision(BaseModel):
    made_by: str
    summary: str
    sim_day: int = Field(ge=1, le=5)


class ProjectState(BaseModel):
    """The single source of truth that every colleague agent reads and writes through tools."""

    simulation_id: str
    sim_day: int = Field(default=1, ge=1, le=5)
    ticket_status: dict[str, TicketStatus] = Field(default_factory=dict)
    decisions: list[Decision] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class CriterionScore(BaseModel):
    skill_id: str
    score: int = Field(ge=1, le=5)
    evidence: list[str] = Field(
        min_length=1, description="Quotes or file:line references from the work."
    )


class Evaluation(BaseModel):
    submission_id: str
    checks: dict[str, bool] = Field(description="Tests, lint and metric thresholds.")
    scores: list[CriterionScore]
    judge_model: str
    feedback: str
