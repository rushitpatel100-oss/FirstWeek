"""Evidence passages: chunking (pure) and incremental indexing (database). Embeddings come
from a deterministic bag-of-words fake, so nothing is downloaded."""

import math
import re
import uuid
import zlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import OperationalError

from firstweek_core.config import Settings
from firstweek_core.db import EMBEDDING_DIM
from firstweek_core.db.models import EvidencePassage, JobPosting, Source
from firstweek_core.db.session import get_engine, session_scope
from firstweek_core.llm import BudgetRegistry, LLMGateway
from firstweek_core.llm.tracing import NoopTracer
from firstweek_research import passages
from firstweek_research.passages import MAX_CHARS, chunk_text, index_evidence, readable

LOCAL_MODEL = "local/BAAI/bge-small-en-v1.5"

# ---------------------------------------------------------------------- chunking


POSTING = """## About the role
We are building an AI assistant for accountants.

## What you'll do
- Build retrieval-augmented generation pipelines over customer documents.
- Design evaluation suites and run them in CI.

Requirements:
- 3+ years of Python
- Experience with LangGraph or similar agent frameworks"""


def test_a_short_posting_is_one_passage_with_its_headings() -> None:
    assert chunk_text(POSTING) == [
        "About the role: We are building an AI assistant for accountants.\n\n"
        "What you'll do:\n"
        "- Build retrieval-augmented generation pipelines over customer documents.\n"
        "- Design evaluation suites and run them in CI.\n\n"
        "Requirements:\n"
        "- 3+ years of Python\n"
        "- Experience with LangGraph or similar agent frameworks"
    ]


def test_long_text_splits_at_paragraphs_and_every_passage_keeps_its_heading() -> None:
    body = "\n\n".join(
        f"Point {i}. " + "Agents call tools and check results. " * 8 for i in range(6)
    )
    passages = chunk_text(f"## Day to day\n{body}")
    assert len(passages) > 1
    assert all(len(p) <= MAX_CHARS for p in passages)
    assert all(p.startswith("Day to day: Point ") for p in passages)  # never mid-paragraph
    assert "".join(passages).count("Point ") == 6  # nothing lost or repeated


def test_an_oversized_paragraph_splits_at_bullets_then_sentences() -> None:
    bullets = "\n".join(f"- Responsibility number {i} " + "with detail " * 10 for i in range(12))
    passages = chunk_text(bullets, max_chars=300)
    assert all(len(p) <= 300 for p in passages)
    assert all(p.startswith("- Responsibility") for p in passages)

    run_on = " ".join(f"Sentence {i} is about evaluation." for i in range(40))
    passages = chunk_text(run_on, max_chars=200)
    assert all(len(p) <= 200 for p in passages)
    assert all(p.startswith("Sentence") and p.endswith(".") for p in passages)


def test_a_line_without_sentence_ends_is_cut_mid_sentence_as_a_last_resort() -> None:
    passages = chunk_text("agents call tools and check results " * 15, max_chars=100)
    assert len(passages) >= 5 and all(len(p) <= 100 for p in passages)


def test_markdown_is_reduced_to_the_words_a_reader_sees() -> None:
    page = (
        "![](https://cdn.example/ai-agents-with-langgraph.jpg)\n\n"
        "The tools are **[LangChain](https://www.langchain.com/)**, *LlamaIndex* and "
        "`pgvector`; see https://example.com/post for more. Keep snake_case and __init__.\n\n"
        "* first bullet\n+ second <br> bullet"
    )
    assert readable(page) == (
        "\n\nThe tools are LangChain, LlamaIndex and pgvector; see for more. "
        "Keep snake_case and __init__.\n\n- first bullet\n- second bullet"
    )
    # The image's file name mentioned LangGraph; the passage a reader would cite does not.
    assert "langgraph" not in " ".join(chunk_text(page)).lower()


def test_leftovers_too_short_to_be_evidence_are_dropped() -> None:
    assert chunk_text("Worth reading: [https://techcrunch.com/a](https://techcrunch.com/a)") == []
    assert chunk_text("Location: #LI-Remote") == []
    assert chunk_text("PROCESS: Final interview with one of our Founding Engineers") != []


def test_a_heading_ending_in_a_colon_is_not_doubled() -> None:
    assert chunk_text(
        "## Experimentation & Evaluation:\nRun experiments on every model we ship."
    ) == ["Experimentation & Evaluation: Run experiments on every model we ship."]


def test_headings_alone_make_no_passages() -> None:
    assert chunk_text("## Benefits\n\nPERKS\n\n# Apply") == []


# ---------------------------------------------------------------------- fakes


def bag_of_words(_name: str, texts: list[str], _kind: str, _cache: str) -> list[list[float]]:
    """Each word lands in a fixed slot, so texts sharing words are close: enough meaning
    for tests, deterministic, and nothing to download."""
    vectors = []
    for t in texts:
        v = [0.0] * EMBEDDING_DIM
        for word in re.findall(r"[a-z]+", t.lower()):
            v[zlib.crc32(word.encode()) % EMBEDDING_DIM] += 1.0
        norm = math.sqrt(sum(x * x for x in v))
        vectors.append([x / norm for x in v] if norm else [1.0] + [0.0] * (EMBEDDING_DIM - 1))
    return vectors


class CountingEmbedder:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, name: str, texts: list[str], kind: str, cache: str) -> list[list[float]]:
        self.calls.append(texts)
        return bag_of_words(name, texts, kind, cache)


def evidence_gateway(embedder: Any = bag_of_words, model: str = LOCAL_MODEL) -> LLMGateway:
    async def no_completions(**_: Any) -> Any:
        raise AssertionError("indexing and search make no completion calls")

    return LLMGateway(
        settings=Settings(_env_file=None, model_embedding=model),
        completion_fn=no_completions,
        tracer=NoopTracer(),
        budgets=BudgetRegistry(Decimal("1")),
        embed_fn=embedder,
    )


# ---------------------------------------------------------------------- database


@pytest.fixture(name="_db")
def db_fixture() -> None:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError:
        pytest.skip("No database available")
    with session_scope() as session:
        session.execute(delete(JobPosting))
        session.execute(delete(Source))


def add_posting(
    body: str,
    *,
    title: str = "GenAI Engineer",
    duplicate: bool = False,
    full_text: bool = True,
    days_since_seen: int = 1,
) -> JobPosting:
    url = f"https://jobs.example/{uuid.uuid4().hex[:8]}"
    with session_scope() as session:
        source = Source(
            url=url,
            tier="posting",
            provider="greenhouse",
            title=title,
            publisher="Acme",
            content_hash=uuid.uuid4().hex,
            content=f"## About Acme\nWe make things.\n\n{body}",
            licence_note="test",
        )
        session.add(source)
        session.flush()
        posting = JobPosting(
            source_id=source.id,
            provider="greenhouse",
            external_id=url,
            title=title,
            company="Acme",
            country="GB",
            is_full_text=full_text,
            is_duplicate=duplicate,
            text=body,
            last_seen_at=datetime.now(UTC) - timedelta(days=days_since_seen),
        )
        session.add(posting)
        session.flush()
        session.expunge(posting)
        return posting


def add_page(content: str, tier: str = "blog", site: str = "blog.example") -> uuid.UUID:
    with session_scope() as session:
        source = Source(
            url=f"https://{site}/{uuid.uuid4().hex[:8]}",
            tier=tier,
            provider="firecrawl",
            title="What an AI engineer does all day",
            publisher="Example Blog",
            content_hash=uuid.uuid4().hex,
            content=content,
            licence_note="test",
        )
        session.add(source)
        session.flush()
        return source.id


def passages_by_source() -> dict[uuid.UUID, list[EvidencePassage]]:
    with session_scope() as session:
        rows = session.scalars(select(EvidencePassage).order_by(EvidencePassage.ordinal)).all()
        session.expunge_all()
    out: dict[uuid.UUID, list[EvidencePassage]] = {}
    for row in rows:
        out.setdefault(row.source_id, []).append(row)
    return out


@pytest.mark.db
@pytest.mark.usefixtures("_db")
async def test_indexing_covers_current_evidence_only_and_is_incremental() -> None:
    live = add_posting(POSTING)
    add_posting("A copy of another posting that also builds LLM agents daily.", duplicate=True)
    add_posting("An Adzuna snippet about building LLM agents for a bank.", full_text=False)
    add_posting("A role that closed long ago, building LLM agents for retail.", days_since_seen=300)
    page = add_page("# Notes\n\nMost days I write evals for our RAG pipeline in pgvector.")
    # Collected before course sellers were excluded: it must not become evidence.
    add_page("Agentic AI engineers build LLM agents; enrol in our Nanodegree.", site="udacity.com")
    embedder = CountingEmbedder()
    gateway = evidence_gateway(embedder)

    first = await index_evidence(gateway)
    assert (first.sources, first.indexed, first.unchanged) == (2, 2, 0)
    stored = passages_by_source()
    assert set(stored) == {live.source_id, page}
    # A posting's passages come from its role text: the company boilerplate is not evidence.
    assert "About Acme" not in stored[live.source_id][0].text
    assert stored[page][0].text.startswith("Notes: Most days")
    assert all(
        p.embedding_model == LOCAL_MODEL and p.embedding is not None and len(p.embedding) == 384
        for ps in stored.values()
        for p in ps
    )
    with session_scope() as session:  # Postgres keeps the keyword index in step by itself
        found = session.scalar(
            select(func.count()).where(
                EvidencePassage.tsv.op("@@")(func.to_tsquery("english", "pipeline"))
            )
        )
    assert found == 2  # stemmed: "pipelines" in the posting, "pipeline" on the blog

    calls_before = len(embedder.calls)
    again = await index_evidence(gateway)
    assert (again.indexed, again.unchanged) == (0, 2)
    assert len(embedder.calls) == calls_before  # nothing re-embedded

    with session_scope() as session:
        session.execute(
            update(JobPosting)
            .where(JobPosting.id == live.id)
            .values(text=POSTING + "\n\n- Mentor junior engineers")
        )
    changed = await index_evidence(gateway)
    assert (changed.indexed, changed.unchanged) == (1, 1)
    assert "Mentor junior engineers" in passages_by_source()[live.source_id][-1].text

    with session_scope() as session:
        session.execute(
            update(JobPosting).where(JobPosting.id == live.id).values(is_duplicate=True)
        )
    pruned = await index_evidence(gateway)
    assert pruned.sources_removed == 1
    assert set(passages_by_source()) == {page}


@pytest.mark.db
@pytest.mark.usefixtures("_db")
async def test_a_new_embedding_model_re_embeds_everything() -> None:
    add_posting(POSTING)
    await index_evidence(evidence_gateway())
    summary = await index_evidence(evidence_gateway(model="local/other/model-384"))
    assert (summary.indexed, summary.unchanged) == (1, 0)
    [passages] = passages_by_source().values()
    assert {p.embedding_model for p in passages} == {"local/other/model-384"}


@pytest.mark.db
@pytest.mark.usefixtures("_db")
async def test_new_chunking_rules_re_chunk_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    add_posting(POSTING)
    await index_evidence(evidence_gateway())
    monkeypatch.setattr(passages, "CHUNKER_VERSION", passages.CHUNKER_VERSION + 1)
    summary = await index_evidence(evidence_gateway())
    assert (summary.indexed, summary.unchanged) == (1, 0)


@pytest.mark.db
@pytest.mark.usefixtures("_db")
async def test_vectors_of_the_wrong_width_are_refused_with_the_fix() -> None:
    add_posting(POSTING)

    def wide(_n: str, texts: list[str], _k: str, _c: str) -> list[list[float]]:
        return [[0.1] * 1536 for _ in texts]

    with pytest.raises(ValueError, match=r"1536-wide.*stores 384.*\.env"):
        await index_evidence(evidence_gateway(wide))
    assert passages_by_source() == {}


def test_hacker_news_comment_chrome_is_removed_but_the_comment_stays() -> None:
    page = (
        "| | | andrei_says_ 11 months ago | parent | prev | next[\u2013]My dismissal indicates "
        "exhaustion from the additional work I would need to do.\n\n"
        "| | afavour 11 months ago | root | parent | next [\u2013]"
        "I have experimented with AI a bunch."
    )
    text = readable(page)
    assert "parent" not in text and "ago" not in text and "|" not in text
    assert "My dismissal indicates exhaustion" in text
    assert "I have experimented with AI a bunch." in text
