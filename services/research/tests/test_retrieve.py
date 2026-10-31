"""Hybrid search: role scoping, the two rankings and how they are fused."""

import pytest
from test_passages import add_page, add_posting, db_fixture, evidence_gateway

from firstweek_core.db.models import JobPosting, PostingRoleMatch
from firstweek_core.db.session import session_scope
from firstweek_research.extract import CLASSIFIER_VERSION
from firstweek_research.passages import index_evidence
from firstweek_research.retrieve import RRF_K, search
from firstweek_research.roles import load_roles
from firstweek_research.store import seed_roles

ROLE = "genai-engineer"
__all__ = ["db_fixture"]  # imported to register the _db fixture here


def _decide(posting: JobPosting, is_match: bool, confidence: float, *, stale: bool = False) -> None:
    role = load_roles()[ROLE]
    with session_scope() as session:
        archetype_id = seed_roles(session, load_roles())[ROLE]
        session.add(
            PostingRoleMatch(
                posting_id=posting.id,
                archetype_id=archetype_id,
                is_match=is_match,
                confidence=confidence,
                reason="test",
                classifier_version=CLASSIFIER_VERSION,
                definition_hash="0000000000000000" if stale else role.definition_hash,
                model="anthropic/claude-haiku-5-5",
            )
        )


@pytest.fixture
async def evidence(_db: None) -> dict[str, str]:
    counted = add_posting("You will build evaluation pipelines that score LLM output quality.")
    _decide(counted, True, 0.9)
    rejected = add_posting("Evaluation pipelines that score LLM output quality, for sales.")
    _decide(rejected, False, 0.9)
    unsure = add_posting("Evaluation of LLM output quality is a small part of this job.")
    _decide(unsure, True, 0.3)  # judged the role, but too unsure to count
    stale = add_posting("Score LLM output quality with evaluation pipelines every day.")
    _decide(stale, True, 0.9, stale=True)  # decided under an old definition
    page = add_page("## Evals\n\nWe store embeddings in pgvector and grade answers weekly.")
    forum = add_page(
        "Hiring managers often ask candidates about prompt injection and how to defend.",
        tier="forum",
    )
    await index_evidence(evidence_gateway())
    return {
        "counted": str(counted.source_id),
        "rejected": str(rejected.source_id),
        "unsure": str(unsure.source_id),
        "stale": str(stale.source_id),
        "page": str(page),
        "forum": str(forum),
    }


@pytest.mark.db
async def test_a_role_search_sees_only_postings_counted_for_the_role(
    evidence: dict[str, str],
) -> None:
    hits = await search(evidence_gateway(), "evaluation pipelines LLM output", role_slug=ROLE)
    found = {str(h.source_id) for h in hits}
    assert evidence["counted"] in found
    assert not found & {evidence["rejected"], evidence["unsure"], evidence["stale"]}
    assert found <= {evidence["counted"], evidence["page"], evidence["forum"]}
    assert str(hits[0].source_id) == evidence["counted"]

    everything = await search(evidence_gateway(), "evaluation pipelines LLM output", k=10)
    assert {evidence["rejected"], evidence["unsure"], evidence["stale"]} <= {
        str(h.source_id) for h in everything
    }


@pytest.mark.db
async def test_hits_say_where_they_came_from_and_how_they_were_found(
    evidence: dict[str, str],
) -> None:
    [top, *_] = await search(evidence_gateway(), "pgvector", role_slug=ROLE)
    assert str(top.source_id) == evidence["page"]
    assert top.tier == "blog" and top.url.startswith("https://blog.example/")
    assert top.publisher == "Example Blog" and top.text.startswith("Evals: We store")
    # Found by both rankings: its fused score is the sum of the two reciprocal ranks.
    assert top.vector_rank == 1 and top.keyword_rank == 1
    assert top.score == pytest.approx(2 / (RRF_K + 1), abs=1e-5)


@pytest.mark.db
async def test_a_question_matches_on_most_of_its_words_not_all(
    evidence: dict[str, str],
) -> None:
    hits = await search(
        evidence_gateway(), "what do interviewers ask about prompt injection risks", k=3
    )
    forum = next(h for h in hits if str(h.source_id) == evidence["forum"])
    assert forum.keyword_rank is not None  # "risks" and "interviewers" are not in it


@pytest.mark.db
async def test_an_empty_index_returns_nothing(_db: None) -> None:
    assert await search(evidence_gateway(), "anything", role_slug=ROLE) == []


@pytest.mark.db
async def test_one_long_page_cannot_crowd_out_other_sources(evidence: dict[str, str]) -> None:
    paragraph = "We run evaluation pipelines on LLM output quality every day, scoring {} " + (
        "answers against rubrics and tracking regressions over time. " * 8
    )
    long_page = add_page("\n\n".join(paragraph.format(i) for i in range(5)))
    await index_evidence(evidence_gateway())

    hits = await search(evidence_gateway(), "evaluation pipelines LLM output quality", k=8)
    from_page = [h for h in hits if h.source_id == long_page]
    assert len(from_page) == 2  # the default cap
    assert len({h.source_id for h in hits}) > 2

    uncapped = await search(
        evidence_gateway(), "evaluation pipelines LLM output quality", k=8, per_source=None
    )
    assert len([h for h in uncapped if h.source_id == long_page]) > 2
