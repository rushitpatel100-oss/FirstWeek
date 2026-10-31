"""Score the role classifier against hand labels (data/eval/classifier_labels.yaml).

Two questions:
1. Accuracy: where a person (or a reviewed draft) says "yes" or "no", does the stored
   decision agree? Reported as agreement, precision, recall and F1 per role, with every
   disagreement listed so a reviewer can decide who is right.
2. Stability (optional, costs money): ask the classifier the same question again. A posting
   whose answer changes between runs is a posting the statistics cannot rely on.

"Counted" means what the statistics use: judged the role with confidence >= MATCH_CONFIDENCE.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from functools import cache
from importlib import resources
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from firstweek_core.db.models import JobPosting, PostingRoleMatch, RoleArchetype, Source
from firstweek_core.db.session import session_scope
from firstweek_core.llm import BudgetExceededError, LLMGateway, StructuredOutputError
from firstweek_research.extract import CLASSIFIER_VERSION, PostingView, classify
from firstweek_research.roles import RoleDefinition, load_roles
from firstweek_research.stats import MATCH_CONFIDENCE, current_match, window_start

Label = Literal["yes", "no", "unsure"]


class LabelledPosting(BaseModel):
    url: str
    company: str
    title: str
    labels: dict[str, Label]
    note: str = ""
    checked: bool = False

    @field_validator("labels", mode="before")
    @classmethod
    def _yaml_booleans(cls, value: dict[str, Any]) -> dict[str, Any]:
        """YAML reads a bare yes/no as true/false; accept either spelling."""
        return {k: ("yes" if v is True else "no" if v is False else v) for k, v in value.items()}


class LabelSet(BaseModel):
    version: int
    labelled_on: date
    postings: list[LabelledPosting] = Field(min_length=1)


@cache
def load_labels() -> LabelSet:
    path = resources.files("firstweek_research") / "data" / "eval" / "classifier_labels.yaml"
    data = yaml.safe_load(path.read_text("utf-8"))
    slugs = set(load_roles())
    postings = []
    for entry in data["postings"]:
        labels = {slug: entry.pop(slug) for slug in sorted(slugs) if slug in entry}
        postings.append({**entry, "labels": labels})
    return LabelSet(version=data["version"], labelled_on=data["labelled_on"], postings=postings)


TITLE_FILTER_REASON = (
    "Never sent to the classifier: the job title does not pass this role's title filter."
)


@dataclass(frozen=True)
class Disagreement:
    company: str
    title: str
    url: str
    label: Label
    counted: bool
    confidence: float | None  # None when the title filter, not the classifier, decided
    reason: str
    note: str
    checked: bool


@dataclass
class RoleScore:
    role: str
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0
    unsure: int = 0
    missing: int = 0  # labelled yes/no, but not decidable in this database (see _verdict)
    by_title_filter: int = 0  # scored postings the title filter rejected before classifying
    disagreements: list[Disagreement] = field(default_factory=list)
    unsure_counted: int = 0  # unsure labels the classifier counted as the role

    @property
    def scored(self) -> int:
        return self.tp + self.fp + self.fn + self.tn

    @property
    def agreement(self) -> float | None:
        return (self.tp + self.tn) / self.scored if self.scored else None

    @property
    def precision(self) -> float | None:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else None

    @property
    def recall(self) -> float | None:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else None

    @property
    def f1(self) -> float | None:
        p, r = self.precision, self.recall
        if p is None or r is None:
            return None
        return 2 * p * r / (p + r) if p + r else 0.0


@dataclass
class Evaluation:
    classifier_version: str
    labels: LabelSet
    roles: list[RoleScore]

    @property
    def checked(self) -> int:
        return sum(p.checked for p in self.labels.postings)


@dataclass(frozen=True)
class _Stored:
    posting: JobPosting
    match: PostingRoleMatch | None


def _decisions(slug: str, urls: list[str]) -> dict[str, _Stored]:
    """Labelled URL -> its posting in this database and the current decision, if any."""
    role = load_roles()[slug]
    with session_scope() as session:
        archetype_id = session.scalar(select(RoleArchetype.id).where(RoleArchetype.slug == slug))
        rows = session.execute(
            select(Source.url, JobPosting)
            .join(JobPosting, JobPosting.source_id == Source.id)
            .where(Source.url.in_(urls))
        ).all()
        postings = {url: posting for url, posting in rows}
        matches = {
            m.posting_id: m
            for m in session.scalars(
                select(PostingRoleMatch).where(
                    PostingRoleMatch.archetype_id == archetype_id,
                    PostingRoleMatch.posting_id.in_([p.id for p in postings.values()]),
                    current_match(role),
                )
            )
        }
        session.expunge_all()
    return {url: _Stored(p, matches.get(p.id)) for url, p in postings.items()}


def _counted(match: PostingRoleMatch) -> bool:
    return match.is_match and match.confidence >= MATCH_CONFIDENCE


def _verdict(role: RoleDefinition, found: _Stored | None) -> PostingRoleMatch | bool | None:
    """What the pipeline decided for a labelled posting.

    A stored decision; False when the posting is eligible but its title never passes the
    role's title filter (the pipeline said no without asking the model); or None when this
    database cannot say: not collected, a duplicate, outside the window, or not classified yet.
    """
    if found is None:
        return None
    if found.match is not None:
        return found.match
    p = found.posting
    eligible = p.is_full_text and not p.is_duplicate and p.last_seen_at >= window_start()
    if eligible and not role.title_matches(p.title):
        return False
    return None


def evaluate(labels: LabelSet | None = None) -> Evaluation:
    labels = labels or load_labels()
    urls = [p.url for p in labels.postings]
    scores = []
    roles = load_roles()
    for slug in sorted(roles):
        score = RoleScore(slug)
        stored = _decisions(slug, urls)
        for item in labels.postings:
            label = item.labels.get(slug)
            if label is None:
                continue
            verdict = _verdict(roles[slug], stored.get(item.url))
            match = verdict if isinstance(verdict, PostingRoleMatch) else None
            if label == "unsure":
                score.unsure += 1
                score.unsure_counted += bool(match and _counted(match))
                continue
            if verdict is None:
                score.missing += 1
                continue
            score.by_title_filter += match is None
            counted = _counted(match) if match else False
            if label == "yes":
                score.tp += counted
                score.fn += not counted
            else:
                score.fp += counted
                score.tn += not counted
            if counted != (label == "yes"):
                score.disagreements.append(
                    Disagreement(
                        company=item.company,
                        title=item.title,
                        url=item.url,
                        label=label,
                        counted=counted,
                        confidence=match.confidence if match else None,
                        reason=match.reason if match else TITLE_FILTER_REASON,
                        note=item.note,
                        checked=item.checked,
                    )
                )
        scores.append(score)
    return Evaluation(CLASSIFIER_VERSION, labels, scores)


# ---------------------------------------------------------------------- stability


@dataclass
class Stability:
    role: str
    postings: int = 0
    flipped: list[tuple[str, str, list[bool]]] = field(default_factory=list)
    failures: int = 0
    checked: int = 0  # progress counter, including failures

    @property
    def flip_rate(self) -> float | None:
        return len(self.flipped) / self.postings if self.postings else None


async def stability(
    gateway: LLMGateway,
    repeats: int,
    *,
    budget_usd: float,
    labels: LabelSet | None = None,
    progress: Callable[[str], None] | None = None,
    concurrency: int = 8,
) -> list[Stability]:
    """Re-asks the classifier `repeats` times per labelled posting and role. Nothing is stored."""
    labels = labels or load_labels()
    roles = load_roles()
    scope = f"eval-stability:{CLASSIFIER_VERSION}"
    gateway.budget(scope, Decimal(str(budget_usd)))
    gate = asyncio.Semaphore(concurrency)
    report = progress or (lambda _: None)

    async def ask(role: RoleDefinition, view: PostingView) -> bool | None:
        async with gate:
            try:
                match, _ = await classify(gateway, role, view, budget_scope=scope)
            except (StructuredOutputError, BudgetExceededError):
                return None
            return match.is_target_role and match.confidence >= MATCH_CONFIDENCE

    async def recheck(s: _Stored, role: RoleDefinition, result: Stability, total: int) -> None:
        p = s.posting
        view = PostingView(str(p.id), str(p.source_id), p.title, p.company, p.text)
        answers = await asyncio.gather(*(ask(role, view) for _ in range(repeats)))
        result.checked += 1
        if result.checked % 25 == 0:
            report(f"    {result.checked}/{total}")
        if any(a is None for a in answers) or s.match is None:
            result.failures += 1
            return
        verdicts = [_counted(s.match), *(a for a in answers if a is not None)]
        result.postings += 1
        if len(set(verdicts)) > 1:
            result.flipped.append((p.company or "?", p.title, verdicts))

    results = []
    for slug in sorted(roles):
        result = Stability(slug)
        decided = [
            s
            for s in _decisions(slug, [p.url for p in labels.postings]).values()
            if s.match is not None
        ]
        report(f"  {slug}: re-asking about {len(decided)} postings, {repeats} times each...")
        await asyncio.gather(*(recheck(s, roles[slug], result, len(decided)) for s in decided))
        result.flipped.sort(key=lambda f: (f[0], f[1]))
        results.append(result)
    return results
