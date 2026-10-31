"""The extraction evaluation: packaged labels and scoring against stored extractions."""

import uuid
from datetime import date

import pytest
from sqlalchemy import delete, text
from sqlalchemy.exc import OperationalError

from firstweek_core.db.models import Extraction, ExtractionRun, JobPosting, Source
from firstweek_core.db.session import get_engine, session_scope
from firstweek_research import evaluate_extraction as xe
from firstweek_research.evaluate import load_labels
from firstweek_research.extract import EXTRACTOR_VERSION
from firstweek_research.taxonomy import load_taxonomy, seed_taxonomy


def test_packaged_extraction_labels_use_known_slugs() -> None:
    labels = xe.load_extraction_labels()
    taxonomy = load_taxonomy()
    assert len(labels.postings) >= 30
    assert len({p.url for p in labels.postings}) == len(labels.postings)
    for p in labels.postings:
        assert set(p.items) <= set(taxonomy.entries), p.url
        assert len(p.items) == len(set(p.items)), p.url
        assert p.note, p.url


def test_extraction_labels_cover_postings_judged_to_be_a_role() -> None:
    # Extraction only runs on postings counted as a role, so labels go where it runs.
    role_labels = {p.url: p for p in load_labels().postings}
    for p in xe.load_extraction_labels().postings:
        assert p.url in role_labels, p.url
        assert "yes" in role_labels[p.url].labels.values(), p.url


# ---------------------------------------------------------------------- database


@pytest.fixture
def _db() -> None:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError:
        pytest.skip("No database available")
    with session_scope() as session:
        session.execute(delete(JobPosting))
        session.execute(delete(Source))


def _stored(
    url: str,
    items: list[tuple[str, str | None]],
    *,
    seniority: str | None = None,
    extracted: bool = True,
    version: str = EXTRACTOR_VERSION,
) -> None:
    """A posting with its extraction. items: (raw label, taxonomy slug or None)."""
    with session_scope() as session:
        ids = seed_taxonomy(session, load_taxonomy())
        source = Source(
            url=url,
            tier="posting",
            provider="ashby",
            content_hash=uuid.uuid4().hex,
            content="text",
            licence_note="test",
        )
        session.add(source)
        session.flush()
        session.add(
            JobPosting(
                source_id=source.id,
                provider="ashby",
                external_id=url,
                title="AI Engineer",
                country="GB",
                is_full_text=True,
                seniority=seniority,
                text="text",
            )
        )
        if not extracted:
            return
        session.add(
            ExtractionRun(
                source_id=source.id,
                extractor_version=version,
                model="anthropic/claude-sonnet-5-5",
                items_kept=len(items),
                items_dropped=0,
            )
        )
        for raw, slug in items:
            kind = load_taxonomy().entries[slug].kind if slug else "skill"
            session.add(
                Extraction(
                    source_id=source.id,
                    kind=kind,
                    raw_text=raw,
                    quote=raw,
                    skill_id=ids[slug] if slug else None,
                    extractor_version=version,
                )
            )


def _labels(*rows: tuple[str, list[str], list[str] | None]) -> xe.ExtractionLabelSet:
    return xe.ExtractionLabelSet(
        version=1,
        labelled_on=date(2026, 10, 31),
        postings=[
            xe.ExtractionLabel(
                url=url,
                company="Acme",
                title=url,
                items=items,
                seniority=seniority,
                note="n",
            )
            for url, items, seniority in rows
        ],
    )


@pytest.mark.db
@pytest.mark.usefixtures("_db")
def test_extraction_is_scored_per_taxonomy_entry() -> None:
    _stored(
        "https://x/a",
        [("Python", "python"), ("RAG", "rag"), ("Kubernetes", "kubernetes"), ("LiteLLM", None)],
        seniority="senior",
    )
    _stored("https://x/not-extracted", [], extracted=False)
    _stored("https://x/empty", [])  # extracted, but nothing found
    _stored("https://x/old", [("Python", "python")], version="extract-posting.v0")
    labels = _labels(
        ("https://x/a", ["python", "rag", "llms"], ["senior"]),
        ("https://x/not-extracted", ["python"], None),
        ("https://x/empty", ["python"], None),
        ("https://x/old", ["python"], None),
        ("https://x/never-collected", ["python"], None),
    )

    result = xe.evaluate_extraction(labels)

    assert sorted(result.missing) == [
        "https://x/never-collected",
        "https://x/not-extracted",
        "https://x/old",  # only an older extractor's output
    ]
    overall = result.rates()
    assert (overall.hits, overall.predicted, overall.gold) == (2, 3, 4)
    assert overall.precision == pytest.approx(2 / 3) and overall.recall == 0.5
    tools, skills = result.rates("tool"), result.rates("skill")
    assert (tools.hits, tools.predicted, tools.gold) == (1, 2, 2)  # python twice, kubernetes
    assert (skills.hits, skills.predicted, skills.gold) == (1, 1, 2)  # rag found, llms missed
    assert dict(result.most_missed()) == {"llms": 1, "python": 1}
    assert dict(result.most_extra()) == {"kubernetes": 1}
    assert result.seniority == (1, 1)
    a = next(p for p in result.postings if p.url == "https://x/a")
    assert a.unmapped == ["LiteLLM"]  # reported, never scored
    assert a.f1 == pytest.approx(2 * 2 / 6)
