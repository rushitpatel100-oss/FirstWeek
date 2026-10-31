"""Suggest ESCO links for taxonomy entries.

ESCO (European Skills, Competences, Qualifications and Occupations) is the EU's public skills
classification. Linking an entry to its ESCO equivalent lets FirstWeek's skill names line up
with an official reference, and marks which entries are FirstWeek's own AI extension.

ESCO search is fuzzy (searching "machine learning" ranks "data mining" first), so links are
never made automatically: this module suggests candidates, a person picks, and the chosen
URI is written into data/taxonomy/ai_skills.yaml where it can be reviewed.
"""

import asyncio
from dataclasses import dataclass

import httpx

from firstweek_research.sources.base import FetchError, request_json
from firstweek_research.taxonomy import SkillEntry, normalize_term

ESCO_API = "https://ec.europa.eu/esco/api"
# The ESCO release the links were chosen against; the API serves the latest by default.
ESCO_VERSION = "v1.2.0"


@dataclass(frozen=True)
class EscoSkill:
    uri: str
    label: str
    description: str

    def same_name_as(self, entry: SkillEntry) -> bool:
        names = {normalize_term(n) for n in [entry.label, *entry.aliases]}
        return normalize_term(self.label) in names


async def search(client: httpx.AsyncClient, text: str, limit: int = 5) -> list[EscoSkill]:
    data = await request_json(
        client,
        "GET",
        f"{ESCO_API}/search",
        params={
            "text": text,
            "type": "skill",
            "language": "en",
            "limit": limit,
            "selectedVersion": ESCO_VERSION,
        },
    )
    return [
        EscoSkill(
            uri=item["uri"],
            label=item.get("title") or "",
            description=(item.get("searchHit") or "")[:160],
        )
        for item in (data.get("_embedded") or {}).get("results") or []
    ]


async def suggest(
    client: httpx.AsyncClient, entry: SkillEntry, *, names: int = 3, limit: int = 4
) -> list[EscoSkill]:
    """Candidates for one entry: searches its label and first aliases, best first, no repeats.
    Candidates whose ESCO name equals one of the entry's names come first."""
    found: dict[str, EscoSkill] = {}
    for name in [entry.label, *entry.aliases][:names]:
        try:
            results = await search(client, name, limit)
        except FetchError:
            continue
        for skill in results:
            found.setdefault(skill.uri, skill)
        await asyncio.sleep(0.2)  # a public API: stay polite
    ranked = list(found.values())
    return sorted(ranked, key=lambda s: not s.same_name_as(entry))
