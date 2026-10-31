"""Hybrid search over evidence passages: meaning (vectors) plus exact words (full text).

Vector search finds passages that say the same thing in other words ("test model quality"
finds "build evaluation pipelines"); keyword search catches exact names the embedding model
blurs (LangGraph, pgvector). The two rankings are merged by reciprocal rank fusion, which
needs no tuning between their very different score scales.

With a role, only evidence for that role is searched: postings counted in its statistics
(judged the role under its current definition, inside the window) plus blogs, forums and
interviews.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import ColumnElement, Text, cast, func, or_, select, text
from sqlalchemy.dialects.postgresql import TSQUERY

from firstweek_core.db.models import EvidencePassage, JobPosting, PostingRoleMatch, Source
from firstweek_core.db.session import session_scope
from firstweek_core.llm import LLMGateway
from firstweek_research.passages import WEB_TIERS, check_width
from firstweek_research.roles import load_roles
from firstweek_research.stats import MATCH_CONFIDENCE, current_match, window_start

RRF_K = 60  # the standard constant: damps the advantage of rank 1 over rank 2
POOL = 40  # candidates taken from each ranking before fusing
EF_SEARCH = 400  # vector-index neighbours examined per query (pgvector default: 40)


@dataclass(frozen=True)
class Hit:
    passage_id: uuid.UUID
    source_id: uuid.UUID
    url: str
    title: str | None
    publisher: str | None
    tier: str
    text: str
    score: float
    vector_rank: int | None
    keyword_rank: int | None


def _allowed(role_slug: str | None, country: str) -> ColumnElement[bool]:
    """Postings from the country that can be in a sample (all of them, or only those
    counted for the role), plus every blog, forum and interview."""
    postings = select(JobPosting.source_id).where(
        JobPosting.country == country,
        JobPosting.is_duplicate.is_(False),
        JobPosting.last_seen_at >= window_start(),
    )
    if role_slug is not None:
        role = load_roles()[role_slug]
        postings = postings.join(
            PostingRoleMatch, PostingRoleMatch.posting_id == JobPosting.id
        ).where(
            current_match(role),
            PostingRoleMatch.is_match.is_(True),
            PostingRoleMatch.confidence >= MATCH_CONFIDENCE,
        )
    return or_(Source.tier.in_(WEB_TIERS), Source.id.in_(postings))


async def search(
    gateway: LLMGateway,
    query: str,
    *,
    role_slug: str | None = None,
    country: str = "GB",
    k: int = 8,
) -> list[Hit]:
    embedded = await gateway.embed([query], kind="query", purpose="search-evidence")
    check_width(embedded, gateway.model_for("embedding"))
    [vector] = embedded
    allowed = _allowed(role_slug, country)
    # Words are OR-ed, so a question finds passages that share most of its words, not only
    # those with all of them; "quoted phrases" still match as phrases.
    tsquery = cast(
        func.replace(cast(func.websearch_to_tsquery("english", query), Text), " & ", " | "),
        TSQUERY,
    )
    with session_scope() as session:
        # The vector index filters after it searches: look at enough neighbours that a
        # role-scoped search still fills its pool.
        session.execute(text(f"SET LOCAL hnsw.ef_search = {EF_SEARCH}"))
        base = select(EvidencePassage.id).join(Source, Source.id == EvidencePassage.source_id)
        by_vector = session.scalars(
            base.where(allowed, EvidencePassage.embedding.is_not(None))
            .order_by(EvidencePassage.embedding.cosine_distance(vector))
            .limit(POOL)
        ).all()
        by_keyword = session.scalars(
            base.where(allowed, EvidencePassage.tsv.op("@@")(tsquery))
            .order_by(func.ts_rank_cd(EvidencePassage.tsv, tsquery).desc())
            .limit(POOL)
        ).all()
        ranks_v = {pid: i for i, pid in enumerate(by_vector, 1)}
        ranks_k = {pid: i for i, pid in enumerate(by_keyword, 1)}
        scores = {
            pid: sum(1 / (RRF_K + r[pid]) for r in (ranks_v, ranks_k) if pid in r)
            for pid in {*ranks_v, *ranks_k}
        }
        top = sorted(scores, key=lambda pid: (-scores[pid], str(pid)))[:k]
        rows = {
            p.id: (p, s)
            for p, s in session.execute(
                select(EvidencePassage, Source)
                .join(Source, Source.id == EvidencePassage.source_id)
                .where(EvidencePassage.id.in_(top))
            )
        }
        return [
            Hit(
                passage_id=pid,
                source_id=rows[pid][1].id,
                url=rows[pid][1].url,
                title=rows[pid][1].title,
                publisher=rows[pid][1].publisher,
                tier=rows[pid][1].tier,
                text=rows[pid][0].text,
                score=round(scores[pid], 5),
                vector_rank=ranks_v.get(pid),
                keyword_rank=ranks_k.get(pid),
            )
            for pid in top
        ]
