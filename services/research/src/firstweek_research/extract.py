"""Role classification and quote-verified extraction.

Two LLM steps, each validated against a contract:
1. classify: is this posting the role? (small model; role-specific)
2. extract: which skills, tools and responsibilities does it ask for? (mid model; done once
   per posting and reused for every role)

Every extracted item must carry a quote that is found verbatim in the posting. Items whose
quote is not found are dropped and counted: that count is our measured hallucination rate.
"""

import re
import unicodedata
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Literal

from firstweek_core.contracts import ExtractedItem, PostingExtraction, RoleMatch
from firstweek_core.llm import LLMGateway
from firstweek_research.roles import RoleDefinition
from firstweek_research.taxonomy import Taxonomy

CLASSIFIER_VERSION = "classify-role.v1"
EXTRACTOR_VERSION = "extract-posting.v1"
MAX_TEXT_CHARS = 12_000  # long postings are cut to bound cost; role text comes first
SPLIT = "=== user ==="
# Output limits include the model's thinking (on by default for Claude 5.5), so they leave
# room well beyond the JSON itself. The gateway doubles them if a reply is still cut off.
CLASSIFY_MAX_TOKENS = 4_000
EXTRACT_MAX_TOKENS = 16_000

ItemKind = Literal["skill", "tool", "responsibility"]


@dataclass(frozen=True)
class PostingView:
    id: str
    source_id: str
    title: str
    company: str | None
    text: str


@dataclass(frozen=True)
class VerifiedItem:
    kind: ItemKind
    label: str
    quote: str
    skill_slug: str | None


@dataclass(frozen=True)
class ExtractionOutcome:
    seniority: str | None
    items: list[VerifiedItem]
    dropped: list[tuple[ItemKind, ExtractedItem]]
    model: str


@cache
def load_prompt(version: str) -> tuple[str, str]:
    """Returns (system, user template) from prompts/<version>.md."""
    path = resources.files("firstweek_research") / "prompts" / f"{version}.md"
    system, user = path.read_text("utf-8").split(SPLIT)
    return system.strip(), user.strip()


_QUOTES = str.maketrans(
    {
        0x2018: "'",  # left single quote
        0x2019: "'",  # right single quote
        0x201C: '"',  # left double quote
        0x201D: '"',  # right double quote
        0x2013: "-",  # en dash
        0x2014: "-",  # em dash
        0x2022: " ",  # bullet
        0x00A0: " ",  # non-breaking space
    }
)


def _canon(text: str) -> str:
    """Forgives only typography and whitespace, never wording."""
    text = unicodedata.normalize("NFKC", text).translate(_QUOTES).casefold()
    return re.sub(r"\s+", " ", text).strip()


def quote_in_text(quote: str, text: str) -> bool:
    q = _canon(quote).strip(" .,;:-\"'")
    return len(q) >= 3 and q in _canon(text)


def verify(
    extraction: PostingExtraction, text: str, taxonomy: Taxonomy
) -> tuple[list[VerifiedItem], list[tuple[ItemKind, ExtractedItem]]]:
    kept: list[VerifiedItem] = []
    dropped: list[tuple[ItemKind, ExtractedItem]] = []
    seen: set[tuple[str, str]] = set()
    groups: list[tuple[ItemKind, list[ExtractedItem]]] = [
        ("skill", extraction.skills),
        ("tool", extraction.tools),
        ("responsibility", extraction.responsibilities),
    ]
    for kind, items in groups:
        for item in items:
            if not quote_in_text(item.quote, text):
                dropped.append((kind, item))
                continue
            slug = taxonomy.lookup(item.label) if kind != "responsibility" else None
            # The taxonomy decides skill versus tool when it knows the term.
            final_kind: ItemKind = taxonomy.entries[slug].kind if slug else kind
            key = (final_kind, slug or item.label.casefold())
            if key in seen:
                continue
            seen.add(key)
            kept.append(VerifiedItem(final_kind, item.label.strip(), item.quote.strip(), slug))
    return kept, dropped


def _clip(text: str) -> str:
    return text if len(text) <= MAX_TEXT_CHARS else text[:MAX_TEXT_CHARS] + "\n[...cut...]"


async def classify(
    gateway: LLMGateway, role: RoleDefinition, posting: PostingView, *, budget_scope: str
) -> tuple[RoleMatch, str]:
    system, user = load_prompt(CLASSIFIER_VERSION)
    result = await gateway.structured(
        purpose="classify-role",
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": user.format(
                    role_name=role.name,
                    role_definition=role.definition,
                    title=posting.title,
                    company=posting.company or "unknown",
                    text=_clip(posting.text),
                ),
            },
        ],
        response_model=RoleMatch,
        tier="small",
        max_tokens=CLASSIFY_MAX_TOKENS,
        budget_scope=budget_scope,
        prompt_version=CLASSIFIER_VERSION,
    )
    assert result.parsed is not None
    return result.parsed, result.model


async def extract(
    gateway: LLMGateway, posting: PostingView, taxonomy: Taxonomy, *, budget_scope: str
) -> ExtractionOutcome:
    system, user = load_prompt(EXTRACTOR_VERSION)
    text = _clip(posting.text)
    result = await gateway.structured(
        purpose="extract-posting",
        messages=[
            {
                "role": "system",
                "content": system.format(
                    skill_vocabulary="; ".join(taxonomy.vocabulary("skill")),
                    tool_vocabulary="; ".join(taxonomy.vocabulary("tool")),
                ),
            },
            {"role": "user", "content": user.format(title=posting.title, text=text)},
        ],
        response_model=PostingExtraction,
        tier="mid",
        max_tokens=EXTRACT_MAX_TOKENS,
        budget_scope=budget_scope,
        prompt_version=EXTRACTOR_VERSION,
    )
    assert result.parsed is not None
    kept, dropped = verify(result.parsed, text, taxonomy)
    return ExtractionOutcome(result.parsed.seniority, kept, dropped, result.model)
