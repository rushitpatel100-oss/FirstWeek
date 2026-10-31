"""Typed contracts. Every LLM output is validated against one of these models."""

from firstweek_core.contracts.research import (
    TIER_WEIGHTS,
    ArchetypeStats,
    Citation,
    Claim,
    DraftCitation,
    DraftClaim,
    ExtractedItem,
    GapItem,
    PostingExtraction,
    ReportSection,
    RoleMatch,
    RoleRealityReport,
    SalaryStat,
    SectionDraft,
    SkillStat,
    Tier,
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
    "DraftCitation",
    "DraftClaim",
    "Evaluation",
    "ExtractedItem",
    "GapItem",
    "PostingExtraction",
    "ProjectBlueprint",
    "ProjectState",
    "ReportSection",
    "RoleMatch",
    "RoleRealityReport",
    "SalaryStat",
    "SectionDraft",
    "SkillStat",
    "Ticket",
    "Tier",
]
