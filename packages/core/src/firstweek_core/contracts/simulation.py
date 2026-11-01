"""Contracts for simulation design: tickets, rubrics and project blueprints."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

TaskType = Literal[
    "code",
    "notebook",
    "design_doc",
    "data_analysis",
    "message",
    "prioritisation",
    "incident_triage",
]


class Criterion(BaseModel):
    skill_id: str
    weight: float = Field(gt=0, le=1)
    anchors: dict[int, str] = Field(description="Score 1-5 -> what that level looks like.")
    checks: list[str] = Field(
        default_factory=list, description="Deterministic checks feeding this score."
    )

    @model_validator(mode="after")
    def _anchors_cover_scale(self) -> "Criterion":
        if set(self.anchors) != {1, 2, 3, 4, 5}:
            raise ValueError("anchors must describe every score from 1 to 5")
        return self


class Ticket(BaseModel):
    key: str = Field(pattern=r"^[A-Z][A-Z0-9]+-\d+$", description="For example GENAI-101.")
    title: str
    description: str
    acceptance_criteria: list[str] = Field(min_length=1)
    task_type: TaskType
    due_day: int = Field(ge=1, le=5)
    skills: list[str] = Field(min_length=1)


class AnswerKey(BaseModel):
    """Hidden from every agent that talks to the user. Only the evaluator reads it."""

    reference_solution_uri: str
    planted_issues: list[str] = Field(description="Bugs and traps the Tech Lead should catch.")
    expected_metrics: dict[str, float] = Field(default_factory=dict)


class ProjectBlueprint(BaseModel):
    archetype: str
    scenario: str
    company_context: str
    tickets: list[Ticket] = Field(min_length=1)
    rubric: list[Criterion] = Field(min_length=1)
    answer_key: AnswerKey

    @model_validator(mode="after")
    def _consistent(self) -> "ProjectBlueprint":
        keys = [t.key for t in self.tickets]
        if len(keys) != len(set(keys)):
            raise ValueError("ticket keys must be unique")
        total = sum(c.weight for c in self.rubric)
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"rubric weights must sum to 1.0, got {total:.3f}")
        rubric_skills = {c.skill_id for c in self.rubric}
        for ticket in self.tickets:
            unknown = set(ticket.skills) - rubric_skills
            if unknown:
                raise ValueError(f"{ticket.key} assesses skills missing from the rubric: {unknown}")
        return self

    def public_view(self) -> dict[str, object]:
        """The blueprint as colleague agents may see it: no answer key."""
        return self.model_dump(exclude={"answer_key"})


class TicketDraft(BaseModel):
    """A ticket as the model writes it. Code assigns the key and checks the rest."""

    title: str = Field(min_length=5, max_length=140)
    description: str = Field(min_length=20)
    acceptance_criteria: list[str] = Field(min_length=2, max_length=6)
    task_type: TaskType
    due_day: int = Field(ge=1, le=5)
    skills: list[str] = Field(min_length=1, max_length=3, description="Skill ids from the list.")


class CriterionDraft(BaseModel):
    skill_id: str
    weight: float = Field(gt=0, description="Relative importance; code scales the set to 1.")
    anchors: list[str] = Field(
        min_length=5,
        max_length=5,
        description="Exactly five entries, in order: what score 1, 2, 3, 4 and 5 work looks like.",
    )
    checks: list[str] = Field(min_length=1, description="Deterministic checks feeding the score.")


class BlueprintDraft(BaseModel):
    """What the model designs. `check_draft` in the simulation service turns it into a
    `ProjectBlueprint` or says what is wrong."""

    company_name: str = Field(min_length=2, max_length=80)
    company_context: str = Field(
        min_length=50, description="The fictional company, in 3-5 sentences."
    )
    scenario: str = Field(min_length=80, description="The situation the person walks into.")
    grounded_in: list[int] = Field(
        min_length=1,
        max_length=3,
        description="Numbers of the pain points the scenario is built on.",
    )
    tickets: list[TicketDraft] = Field(min_length=3, max_length=5)
    rubric: list[CriterionDraft] = Field(min_length=3, max_length=6)
    planted_issues: list[str] = Field(
        min_length=3, max_length=6, description="Problems hidden in the starter material."
    )
    expected_metrics: dict[str, float] = Field(default_factory=dict)
