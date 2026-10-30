"""Contracts for the research pipeline and the Role Reality Report.

Every LLM output in the research pipeline is validated against one of these models.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator

Tier = Literal["posting", "blog", "forum", "interview"]
Level = Literal["junior", "mid", "senior", "lead", "principal"]
Verification = Literal["supported", "partial", "unsupported"]
TrustLevel = Literal["golden", "on_demand"]

TIER_WEIGHTS: dict[Tier, float] = {"posting": 1.0, "blog": 0.8, "forum": 0.5, "interview": 1.0}


class Citation(BaseModel):
    source_url: HttpUrl
    tier: Tier
    quote: str = Field(min_length=1, max_length=300, description="Exact supporting text.")
    published: date | None = None


class Claim(BaseModel):
    text: str = Field(min_length=1)
    citations: list[Citation] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    verification: Verification

    @property
    def confidence_label(self) -> Literal["high", "medium", "low"]:
        if self.confidence >= 0.75:
            return "high"
        if self.confidence >= 0.5:
            return "medium"
        return "low"


class ExtractedItem(BaseModel):
    label: str = Field(min_length=1, description="As written in the source.")
    quote: str = Field(min_length=1, description="Exact span, used later for verification.")
    skill_id: str | None = Field(default=None, description="Filled in by normalisation.")


class PostingExtraction(BaseModel):
    is_target_role: bool
    seniority: Level
    responsibilities: list[ExtractedItem]
    tools: list[ExtractedItem]
    skills: list[ExtractedItem]


class SkillStat(BaseModel):
    skill_id: str
    label: str
    share: float = Field(ge=0, le=1, description="Share of postings mentioning it.")
    ci_low: float = Field(ge=0, le=1)
    ci_high: float = Field(ge=0, le=1)
    n: int = Field(ge=1, description="Sample size.")

    @model_validator(mode="after")
    def _interval_contains_share(self) -> "SkillStat":
        if not self.ci_low <= self.share <= self.ci_high:
            raise ValueError("share must lie inside its confidence interval")
        return self


class GapItem(BaseModel):
    skill_id: str
    status: Literal["have", "transferable", "missing"]
    reason: str


class RoleRealityReport(BaseModel):
    archetype: str
    trust_level: TrustLevel
    version: int = Field(ge=1)
    country: str = Field(min_length=2, max_length=2, description="ISO 3166-1 alpha-2.")
    sample_size: int = Field(ge=0)
    date_range: tuple[date, date]
    summary: list[Claim]
    asked_for: list[SkillStat]
    day_to_day: list[Claim]
    typical_week: list[Claim]
    pain_points: list[Claim]
    skill_gap: list[GapItem] | None = None

    @model_validator(mode="after")
    def _dates_in_order(self) -> "RoleRealityReport":
        if self.date_range[0] > self.date_range[1]:
            raise ValueError("date_range must run from earlier to later")
        return self
