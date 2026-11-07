"""Contracts for the research pipeline and the Role Reality Report.

Every LLM output in the research pipeline is validated against one of these models.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator

Tier = Literal["posting", "blog", "forum", "interview"]
ReportSection = Literal["summary", "responsibilities", "day_to_day", "typical_week", "pain_points"]
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
    """One skill, tool or responsibility, exactly as an LLM extracted it."""

    label: str = Field(
        min_length=1,
        max_length=120,
        description="Short canonical name. Use the vocabulary label when one applies.",
    )
    quote: str = Field(
        min_length=1,
        max_length=300,
        description="Exact, verbatim span from the posting that supports this item.",
    )


class PostingExtraction(BaseModel):
    """What a posting asks for. Independent of any role, so it is extracted once."""

    seniority: Level | None = Field(description="null if the posting does not make it clear")
    responsibilities: list[ExtractedItem] = Field(max_length=25)
    tools: list[ExtractedItem] = Field(max_length=40)
    skills: list[ExtractedItem] = Field(max_length=40)


class RoleMatch(BaseModel):
    """Does this posting describe the target role, judged against its definition?"""

    is_target_role: bool
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=400)


class SkillStat(BaseModel):
    skill_id: str
    label: str
    count: int = Field(ge=0, description="Postings mentioning it.")
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


class GapDraftItem(BaseModel):
    """One skill's gap as the model judges it. Code keeps 'have' and 'transferable' only when
    the quoted words are really in the person's background."""

    skill_id: str = Field(description="An id from the skills list.")
    status: Literal["have", "transferable", "missing"]
    background_quote: str | None = Field(
        default=None,
        max_length=200,
        description="Words copied exactly from the background. Required for have and "
        "transferable; null for missing.",
    )
    reason: str = Field(min_length=3, max_length=250, description="One short sentence.")


class GapReply(BaseModel):
    items: list[GapDraftItem] = Field(max_length=40)


class DraftCitation(BaseModel):
    """A claim's support, as the report writer gives it: a passage label and an exact quote."""

    passage: str = Field(pattern=r"^P[0-9]+$", description="Label of a passage above, e.g. P3")
    quote: str = Field(
        min_length=3,
        max_length=300,
        description="Copied character for character from that passage, 5 to 40 words.",
    )


class DraftClaim(BaseModel):
    text: str = Field(min_length=10, max_length=400, description="One sentence.")
    citations: list[DraftCitation] = Field(min_length=1, max_length=3)


class SectionDraft(BaseModel):
    """One section of a Role Reality Report, written only from the passages it was given."""

    claims: list[DraftClaim] = Field(max_length=8)
    not_covered: str | None = Field(
        default=None,
        max_length=400,
        description="What this section should cover but the passages do not support. null if none.",
    )


# ---- Verification: a model from another family checks each claim (ADR 0014) ----

CitationVerdict = Literal["supports", "partly", "does_not_support", "contradicts"]


class CitationCheck(BaseModel):
    passage: str = Field(pattern=r"^P[0-9]+$", description="A passage the claim cites.")
    verdict: CitationVerdict


class ClaimCheck(BaseModel):
    claim: str = Field(pattern=r"^C[0-9]+$", description="The claim's label, e.g. C1.")
    citations: list[CitationCheck] = Field(min_length=1, max_length=3)
    verification: Verification
    reason: str = Field(
        min_length=3,
        max_length=400,
        description="One sentence. For partial or unsupported: what is missing or overstated.",
    )


class VerifierReply(BaseModel):
    checks: list[ClaimCheck] = Field(max_length=12)


class RemovedClaim(BaseModel):
    section: ReportSection
    text: str
    stage: Literal["checks", "verifier", "review"]
    reason: str


class ReportProvenance(BaseModel):
    """How a stored report was made, and what was left out of it."""

    stats_version: int
    writer_model: str
    writer_prompt: str
    verifier_model: str
    verifier_prompt: str
    cost_usd: float
    removed: list[RemovedClaim] = Field(default_factory=list)
    method: Literal["pipeline", "researched"] = Field(
        default="pipeline",
        description="pipeline: written and checked by models (ADR 0013/0014). researched: "
        "researched in one session and kept in the repository, quotes checked by code (ADR 0027).",
    )


class RoleRealityReport(BaseModel):
    archetype: str
    trust_level: TrustLevel
    version: int = Field(ge=1)
    country: str = Field(min_length=2, max_length=2, description="ISO 3166-1 alpha-2.")
    sample_size: int = Field(ge=0)
    date_range: tuple[date, date]
    summary: list[Claim]
    asked_for: list[SkillStat]
    responsibilities: list[Claim] = Field(
        default_factory=list, description="What job postings say the work involves (tier 1)."
    )
    day_to_day: list[Claim]
    typical_week: list[Claim]
    pain_points: list[Claim]
    skill_gap: list[GapItem] | None = None
    provenance: ReportProvenance | None = None

    @model_validator(mode="after")
    def _dates_in_order(self) -> "RoleRealityReport":
        if self.date_range[0] > self.date_range[1]:
            raise ValueError("date_range must run from earlier to later")
        return self


class SalaryStat(BaseModel):
    currency: str
    postings: int = Field(ge=1)
    median_min: float
    median_max: float


class ArchetypeStats(BaseModel):
    """Statistics for one role from one research run. Every number carries its sample."""

    role: str
    country: str
    sample_size: int = Field(ge=0, description="Unique full-text postings judged to be the role")
    repeat_postings_merged: int = Field(
        default=0, ge=0, description="Same employer and title advertised again; counted once"
    )
    employers: int = Field(ge=0)
    date_range: tuple[date, date] | None
    sources: dict[str, int] = Field(description="Postings in the sample per provider")
    skills: list[SkillStat]
    tools: list[SkillStat]
    seniority: dict[str, int]
    salary: list[SalaryStat]
    demand_snippets: int = Field(ge=0, description="Adzuna snippet postings for the role's titles")
    unverified_items_dropped: int = Field(
        ge=0, description="Extracted items whose quote was not found in the posting"
    )
    unmapped_terms: int = Field(ge=0, description="Labels not yet in the skills taxonomy")
    classifier_version: str
    extractor_version: str
    definition_hash: str | None = Field(
        default=None, description="Version of the role definition the sample was judged against"
    )
    window_days: int | None = Field(
        default=None, ge=1, description="Postings seen open within this many days of the run"
    )
