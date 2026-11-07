"""Find taxonomy skills in a posting's text by keyword, with no model call.

The free counterpart to quote-verified extraction (ADR 0027): a skill counts for a posting
when one of its names appears in the posting's text. It counts mentions, as `SkillStat`
says, so it is coarser than extraction. Names that mean other things in job ads are left
out ('search', 'cloud', 'CV', 'Go to market'), a few clearer phrasings are added, and an
AI vendor's own name never counts in its own postings.
"""

import re
from dataclasses import dataclass
from functools import cache

from firstweek_research.taxonomy import load_taxonomy

# Names that, alone, mostly mean something else in a job ad.
AMBIGUOUS = frozenset(
    {
        "agents",  # 'human agents', 'our AI agents accelerate your impact' (benefits text)
        "analytics",
        "anthropic",  # investors and partners; 'Claude' still counts
        "architecture",
        "cloud",
        "collaboration",
        "cv",  # curriculum vitae
        "dl",
        "experimentation",
        "experiments",
        "github",  # 'link your GitHub'
        "infrastructure",
        "js",
        "memory management",  # C++ work, not agent memory
        "node",
        "phoenix",
        "ranking",
        "research",
        "scalability",
        "search",
        "security",
        "testing",  # 'A/B testing', 'testing ideas'
        "torch",
        "transformers",
        "ts",
    }
)

# Clearer phrasings the taxonomy does not list, by skill.
EXTRA: dict[str, tuple[str, ...]] = {
    "ai-agents": (
        "agentic",
        "AI agent",
        "AI agents",
        "coding agent",
        "agent loop",
        "agent harness",
    ),
    "llm-evaluation": ("eval",),
    "cross-functional-collaboration": ("cross-functional", "cross functional"),
    "go": ("Golang",),
}

# A vendor's own name in its own postings is not a skill it asks for.
OWN_NAMES: dict[str, frozenset[str]] = {
    "anthropic-api": frozenset({"anthropic"}),
    "openai-api": frozenset({"openai"}),
    "databricks": frozenset({"databricks"}),
    "snowflake": frozenset({"snowflake"}),
    "mongodb": frozenset({"mongodb"}),
    "elasticsearch": frozenset({"elastic"}),
}

_EDGE_BEFORE = r"(?<![A-Za-z0-9])"
_EDGE_AFTER = r"(?![A-Za-z0-9+#])"
# 'Go' is a language only next to other languages: 'Python, Go', 'Go/Rust', '(Go)'.
_GO = re.compile(r"(?:(?<=, )|(?<=/)|(?<=\()|(?<=and )|(?<=or ))Go(?=[,/)]|\s+(?:and|or)\b|$)")


def _with_case(name: str, kind: str) -> bool:
    """Acronyms and one-word product names keep their case: 'Spark' the tool, not 'spark'
    the verb. Phrases and ordinary words match in any case."""
    if " " in name:
        return False
    return (
        len(name) <= 4
        or any(ch.isupper() for ch in name[1:])
        or (kind == "tool" and name[:1].isupper())
    )


@cache
def _patterns() -> dict[str, re.Pattern[str]]:
    taxonomy = load_taxonomy()
    found: dict[str, re.Pattern[str]] = {}
    for slug, entry in taxonomy.entries.items():
        names = [entry.label, *entry.aliases, *EXTRA.get(slug, ())]
        names = [n for n in names if n.lower() not in AMBIGUOUS and n != "Go"]
        sensitive = [re.escape(n) for n in names if _with_case(n, entry.kind)]
        insensitive = [
            re.escape(n).replace(r"\ ", r"[\s-]+") for n in names if not _with_case(n, entry.kind)
        ]
        parts = []
        if insensitive:
            parts.append(f"(?i:{'|'.join(sorted(insensitive, key=len, reverse=True))})")
        if sensitive:
            parts.append("|".join(sorted(sensitive, key=len, reverse=True)))
        if not parts:
            continue
        tail = r"(?!Script)" if slug == "java" else ""
        found[slug] = re.compile(f"{_EDGE_BEFORE}(?:{'|'.join(parts)}){_EDGE_AFTER}{tail}")
    return found


@dataclass(frozen=True)
class Mention:
    skill_id: str
    words: str  # the words that matched, exactly as written in the posting


def find_skills(text: str, company: str) -> list[Mention]:
    """Every taxonomy skill named in the text, once each, with the first words that matched."""
    own = company.lower()
    mentions: list[Mention] = []
    for slug, pattern in _patterns().items():
        if any(name in own for name in OWN_NAMES.get(slug, frozenset())):
            continue
        match = pattern.search(text)
        if match is None and slug == "go":
            match = _GO.search(text)
        if match is not None:
            mentions.append(Mention(slug, match.group(0)))
    return mentions
