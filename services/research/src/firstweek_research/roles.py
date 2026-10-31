"""Role definitions and resolution: map whatever title a user types to a known role.

Golden roles live as YAML in `data/roles/`. Resolution never guesses silently: it returns
an exact match, a confident fuzzy match, a short list of suggestions, or nothing (in which
case the pipeline can research the title as a new on-demand role).
"""

import hashlib
import re
from dataclasses import dataclass, field
from functools import cache
from importlib import resources
from typing import Literal

import yaml
from pydantic import BaseModel, Field
from rapidfuzz import fuzz, process

# Words that describe level or contract, not the role itself.
_LEVEL_WORDS = re.compile(
    r"\b(senior|sr|junior|jr|graduate|grad|intern|internship|mid|mid-level|lead|principal|"
    r"staff|head of|associate|entry[- ]level|i{1,3}|iv|contract|contractor|freelance|"
    r"permanent|remote|hybrid)\b"
)
_PUNCT = re.compile(r"[^a-z0-9+#\s]")
_SPACES = re.compile(r"\s+")

FUZZY_ACCEPT = 90  # at or above: resolved
FUZZY_SUGGEST = 70  # between suggest and accept: ask which one was meant


class RoleDefinition(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    name: str
    trust_level: Literal["golden", "on_demand"]
    reviewed: bool = False
    definition: str = Field(min_length=40)
    aliases: list[str] = Field(min_length=1)
    title_patterns: list[str] = Field(min_length=1)
    web_queries: list[str] = Field(default_factory=list)

    @property
    def definition_hash(self) -> str:
        """Changes whenever the definition's wording changes, so classifier decisions made
        against an older definition are re-checked rather than reused."""
        return hashlib.sha256(" ".join(self.definition.split()).encode()).hexdigest()[:16]

    def compiled_patterns(self) -> list[re.Pattern[str]]:
        return [re.compile(p, re.IGNORECASE) for p in self.title_patterns]

    def title_matches(self, title: str) -> bool:
        """Job-board pre-filter. Deliberately loose; the classifier decides precisely later."""
        return any(p.search(title) for p in self.compiled_patterns())

    def queries(self) -> list[str]:
        return [q.format(name=self.name) for q in self.web_queries]


def normalize_title(title: str) -> str:
    """'Senior Gen-AI Engineer (London, Hybrid)' -> 'gen ai engineer'."""
    text = re.sub(r"\(.*?\)", " ", title.lower())  # drop bracketed notes
    text = text.split(" - ")[0] if " - " in text else text  # 'X - London' -> 'X'
    text = _PUNCT.sub(" ", text)
    text = _LEVEL_WORDS.sub(" ", text)
    return _SPACES.sub(" ", text).strip()


@cache
def load_roles() -> dict[str, RoleDefinition]:
    roles: dict[str, RoleDefinition] = {}
    folder = resources.files("firstweek_research") / "data" / "roles"
    for entry in sorted(folder.iterdir(), key=lambda e: e.name):
        if entry.name.endswith(".yaml"):
            role = RoleDefinition.model_validate(yaml.safe_load(entry.read_text("utf-8")))
            roles[role.slug] = role
    _check_aliases_unique(roles)
    return roles


def _check_aliases_unique(roles: dict[str, RoleDefinition]) -> None:
    seen: dict[str, str] = {}
    for role in roles.values():
        for alias in [role.name, *role.aliases]:
            key = normalize_title(alias)
            if seen.get(key, role.slug) != role.slug:
                raise ValueError(f"Alias '{alias}' belongs to both {seen[key]} and {role.slug}")
            seen[key] = role.slug


@dataclass(frozen=True)
class Suggestion:
    slug: str
    matched_alias: str
    score: float


@dataclass(frozen=True)
class Resolution:
    query: str
    slug: str | None
    method: Literal["exact", "fuzzy", "none"]
    score: float
    suggestions: list[Suggestion] = field(default_factory=list)

    @property
    def resolved(self) -> bool:
        return self.slug is not None


def resolve_role(title: str, roles: dict[str, RoleDefinition] | None = None) -> Resolution:
    roles = roles if roles is not None else load_roles()
    alias_to_slug: dict[str, str] = {}
    display: dict[str, str] = {}
    for role in roles.values():
        for alias in [role.name, *role.aliases]:
            key = normalize_title(alias)
            alias_to_slug[key] = role.slug
            display[key] = alias

    query = normalize_title(title)
    if not query:
        return Resolution(title, None, "none", 0.0)
    if query in alias_to_slug:
        return Resolution(title, alias_to_slug[query], "exact", 100.0)

    # token_sort_ratio, not token_set_ratio: 'ai engineer' must not fully match
    # 'agentic ai engineer' just because one is a subset of the other.
    matches = process.extract(query, list(alias_to_slug), scorer=fuzz.token_sort_ratio, limit=8)
    best_per_role: dict[str, Suggestion] = {}
    for alias_key, score, _ in matches:
        slug = alias_to_slug[alias_key]
        if score >= FUZZY_SUGGEST and slug not in best_per_role:
            best_per_role[slug] = Suggestion(slug, display[alias_key], float(score))
    suggestions = sorted(best_per_role.values(), key=lambda s: -s.score)

    if suggestions and suggestions[0].score >= FUZZY_ACCEPT:
        clear_winner = len(suggestions) == 1 or suggestions[1].score < FUZZY_ACCEPT
        if clear_winner:
            top = suggestions[0]
            return Resolution(title, top.slug, "fuzzy", top.score, suggestions)
    return Resolution(
        title, None, "none", suggestions[0].score if suggestions else 0.0, suggestions
    )
