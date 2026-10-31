"""The skills taxonomy, and mapping extracted labels onto it.

Mapping is deliberately conservative: an exact match on a label or alias, or a very close
spelling (for typos and plurals). Anything else stays unmapped and goes to a review queue
rather than being forced onto the nearest skill.
"""

import re
import uuid
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Literal

import yaml
from pydantic import BaseModel, Field
from rapidfuzz import fuzz, process
from sqlalchemy import select
from sqlalchemy.orm import Session

from firstweek_core.db.models import TaxonomySkill

FUZZY_MIN = 92  # very close spellings only ('pytorh' -> PyTorch), never related concepts
FUZZY_MIN_LENGTH = 5  # short names ('Go', 'Git', 'SQL') must match exactly


ESCO_URI = r"^http://data\.europa\.eu/esco/skill/[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$"


class SkillEntry(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    label: str
    kind: Literal["skill", "tool"]
    aliases: list[str] = Field(default_factory=list)
    # The equivalent ESCO skill, when one exists (see data/taxonomy header). None means the
    # entry is part of FirstWeek's AI extension: ESCO has no equivalent concept yet.
    esco_uri: str | None = Field(default=None, pattern=ESCO_URI)


def normalize_term(term: str) -> str:
    """'Retrieval-Augmented Generation (RAG)' -> 'retrieval augmented generation rag'."""
    text = term.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9+#./ ]", " ", text)
    text = re.sub(r"(?<!\w)\.|\.(?!\w)", " ", text)  # keep dots inside 'next.js'
    return re.sub(r"\s+", " ", text).strip()


@dataclass(frozen=True)
class Taxonomy:
    entries: dict[str, SkillEntry]
    index: dict[str, str]  # normalised label or alias -> slug

    def lookup(self, label: str) -> str | None:
        key = normalize_term(label)
        if not key:
            return None
        if key in self.index:
            return self.index[key]
        # 'RAG (retrieval-augmented generation)' -> try the part before the bracket too
        head = normalize_term(re.sub(r"\(.*?\)", " ", label))
        if head in self.index:
            return self.index[head]
        if len(key) < FUZZY_MIN_LENGTH:
            return None
        candidates = [k for k in self.index if len(k) >= FUZZY_MIN_LENGTH]
        best = process.extractOne(key, candidates, scorer=fuzz.ratio, score_cutoff=FUZZY_MIN)
        return self.index[best[0]] if best else None

    def vocabulary(self, kind: Literal["skill", "tool"]) -> list[str]:
        return sorted(e.label for e in self.entries.values() if e.kind == kind)


@cache
def load_taxonomy() -> Taxonomy:
    path = resources.files("firstweek_research") / "data" / "taxonomy" / "ai_skills.yaml"
    raw = yaml.safe_load(path.read_text("utf-8"))["skills"]
    entries = {e.slug: e for e in (SkillEntry.model_validate(item) for item in raw)}
    if len(entries) != len(raw):
        raise ValueError("Duplicate slug in the skills taxonomy")
    uris = [e.esco_uri for e in entries.values() if e.esco_uri]
    if len(uris) != len(set(uris)):
        raise ValueError("Two taxonomy entries link to the same ESCO skill")
    index: dict[str, str] = {}
    for entry in entries.values():
        for name in [entry.slug.replace("-", " "), entry.label, *entry.aliases]:
            key = normalize_term(name)
            if index.get(key, entry.slug) != entry.slug:
                raise ValueError(f"'{name}' maps to both {index[key]} and {entry.slug}")
            index[key] = entry.slug
    return Taxonomy(entries=entries, index=index)


def seed_taxonomy(session: Session, taxonomy: Taxonomy | None = None) -> dict[str, uuid.UUID]:
    """Create or update taxonomy rows; returns slug -> row id."""
    taxonomy = taxonomy or load_taxonomy()
    existing = {s.slug: s for s in session.scalars(select(TaxonomySkill))}
    for entry in taxonomy.entries.values():
        row = existing.get(entry.slug)
        if row is None:
            row = TaxonomySkill(slug=entry.slug)
            session.add(row)
            existing[entry.slug] = row
        row.label, row.kind, row.aliases = entry.label, entry.kind, entry.aliases
        row.esco_uri = entry.esco_uri
        row.origin = "esco" if entry.esco_uri else "ai_extension"
    session.flush()
    return {slug: row.id for slug, row in existing.items()}
