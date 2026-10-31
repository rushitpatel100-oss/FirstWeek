"""Score the extraction step against hand labels (data/eval/extraction_labels.yaml).

Question: for each labelled posting, did extraction find the skills and tools the posting
asks for (recall), and is what it found actually there (precision)? Compared at the level of
taxonomy entries, because that is what the statistics count. Labels the taxonomy does not
know yet are reported separately: they are neither right nor wrong until someone maps them.

Targets from the build plan: precision 0.85 or more, recall 0.75 or more.
"""

import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from functools import cache
from importlib import resources

import yaml
from pydantic import BaseModel, Field
from sqlalchemy import select

from firstweek_core.contracts.research import Level
from firstweek_core.db.models import (
    Extraction,
    ExtractionRun,
    JobPosting,
    Source,
    TaxonomySkill,
)
from firstweek_core.db.session import session_scope
from firstweek_research.extract import EXTRACTOR_VERSION
from firstweek_research.taxonomy import load_taxonomy

PRECISION_TARGET = 0.85
RECALL_TARGET = 0.75


class ExtractionLabel(BaseModel):
    url: str
    company: str
    title: str
    seniority: list[Level] | None = None  # accepted answers; None: not scored
    items: list[str] = Field(min_length=1)
    note: str = ""
    checked: bool = False


class ExtractionLabelSet(BaseModel):
    version: int
    labelled_on: date
    postings: list[ExtractionLabel] = Field(min_length=1)


@cache
def load_extraction_labels() -> ExtractionLabelSet:
    path = resources.files("firstweek_research") / "data" / "eval" / "extraction_labels.yaml"
    return ExtractionLabelSet.model_validate(yaml.safe_load(path.read_text("utf-8")))


@dataclass
class PostingScore:
    company: str
    title: str
    url: str
    gold: set[str]
    predicted: set[str]
    unmapped: list[str]
    seniority_gold: list[str] | None
    seniority_predicted: str | None

    @property
    def missed(self) -> set[str]:
        return self.gold - self.predicted

    @property
    def extra(self) -> set[str]:
        return self.predicted - self.gold

    @property
    def f1(self) -> float:
        hits = len(self.gold & self.predicted)
        total = len(self.gold) + len(self.predicted)
        return 2 * hits / total if total else 1.0


@dataclass(frozen=True)
class Rates:
    hits: int
    predicted: int
    gold: int

    @property
    def precision(self) -> float | None:
        return self.hits / self.predicted if self.predicted else None

    @property
    def recall(self) -> float | None:
        return self.hits / self.gold if self.gold else None

    @property
    def f1(self) -> float | None:
        p, r = self.precision, self.recall
        if p is None or r is None:
            return None
        return 2 * p * r / (p + r) if p + r else 0.0


@dataclass
class ExtractionEvaluation:
    extractor_version: str
    labels: ExtractionLabelSet
    postings: list[PostingScore] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)  # labelled, but not extracted here

    def rates(self, kind: str | None = None) -> Rates:
        """Micro-averaged over every scored posting; kind is 'skill', 'tool' or None (both)."""
        entries = load_taxonomy().entries

        def keep(slug: str) -> bool:
            return kind is None or (slug in entries and entries[slug].kind == kind)

        hits = predicted = gold = 0
        for p in self.postings:
            g = {s for s in p.gold if keep(s)}
            pr = {s for s in p.predicted if keep(s)}
            hits += len(g & pr)
            predicted += len(pr)
            gold += len(g)
        return Rates(hits, predicted, gold)

    @property
    def seniority(self) -> tuple[int, int]:
        """(correct, scored) over postings whose label settles the level."""
        scored = [p for p in self.postings if p.seniority_gold]
        correct = sum(p.seniority_predicted in (p.seniority_gold or []) for p in scored)
        return correct, len(scored)

    def most_missed(self, n: int = 10) -> list[tuple[str, int]]:
        return Counter(s for p in self.postings for s in p.missed).most_common(n)

    def most_extra(self, n: int = 10) -> list[tuple[str, int]]:
        return Counter(s for p in self.postings for s in p.extra).most_common(n)

    @property
    def checked(self) -> int:
        return sum(p.checked for p in self.labels.postings)


def evaluate_extraction(labels: ExtractionLabelSet | None = None) -> ExtractionEvaluation:
    labels = labels or load_extraction_labels()
    result = ExtractionEvaluation(EXTRACTOR_VERSION, labels)
    urls = [p.url for p in labels.postings]
    with session_scope() as session:
        sources = {
            url: sid
            for url, sid in session.execute(
                select(Source.url, Source.id).where(Source.url.in_(urls))
            )
        }
        extracted = set(
            session.scalars(
                select(ExtractionRun.source_id).where(
                    ExtractionRun.source_id.in_(sources.values()),
                    ExtractionRun.extractor_version == EXTRACTOR_VERSION,
                )
            )
        )
        slug_of = {
            skill_id: slug
            for skill_id, slug in session.execute(select(TaxonomySkill.id, TaxonomySkill.slug))
        }
        rows = session.execute(
            select(Extraction.source_id, Extraction.skill_id, Extraction.raw_text).where(
                Extraction.source_id.in_(extracted),
                Extraction.extractor_version == EXTRACTOR_VERSION,
                Extraction.kind.in_(["skill", "tool"]),
            )
        ).all()
        seniority = {
            sid: level
            for sid, level in session.execute(
                select(JobPosting.source_id, JobPosting.seniority).where(
                    JobPosting.source_id.in_(extracted)
                )
            )
        }
    predicted: dict[uuid.UUID, set[str]] = {sid: set() for sid in extracted}
    unmapped: dict[uuid.UUID, list[str]] = {sid: [] for sid in extracted}
    for source_id, skill_id, raw in rows:
        if skill_id is not None and skill_id in slug_of:
            predicted[source_id].add(slug_of[skill_id])
        else:
            unmapped[source_id].append(raw)
    for item in labels.postings:
        sid = sources.get(item.url)
        if sid is None or sid not in extracted:
            result.missing.append(item.url)
            continue
        result.postings.append(
            PostingScore(
                company=item.company,
                title=item.title,
                url=item.url,
                gold=set(item.items),
                predicted=predicted[sid],
                unmapped=sorted(set(unmapped[sid])),
                seniority_gold=list(item.seniority) if item.seniority else None,
                seniority_predicted=seniority.get(sid),
            )
        )
    return result
