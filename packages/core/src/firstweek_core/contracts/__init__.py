"""Typed contracts. Every LLM output is validated against one of these models."""

from firstweek_core.contracts.research import (
    TIER_WEIGHTS,
    ArchetypeStats,
    Citation,
    Claim,
    ExtractedItem,
    GapItem,
    PostingExtraction,
    RoleMatch,
    RoleRealityReport,
    SalaryStat,
    SkillStat,
)
from firstweek_core.contracts.runtime import CriterionScore, Decision, Evaluation, ProjectState
from firstweek_core.contracts.simulation import AnswerKey, Criterion, ProjectBlueprint, Ticket

__all__ = [
    "TIER_WEIGHTS",
    "AnswerKey",
    "ArchetypeStats",
    "Citation",
    "Claim",
    "Criterion",
    "CriterionScore",
    "Decision",
    "Evaluation",
    "ExtractedItem",
    "GapItem",
    "PostingExtraction",
    "ProjectBlueprint",
    "ProjectState",
    "RoleMatch",
    "RoleRealityReport",
    "SalaryStat",
    "SkillStat",
    "Ticket",
]
