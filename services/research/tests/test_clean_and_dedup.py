from datetime import date

import pytest

from firstweek_research.clean import clean_posting, content_hash, html_to_text
from firstweek_research.dedup import DedupDoc, find_duplicates
from firstweek_research.locations import in_country

POSTING_HTML = """
<p><strong>About Acme</strong></p><p>Acme is the leading platform for widgets.</p>
<h2>About the role</h2><p>You will build RAG pipelines in Python.</p>
<p><strong>What you'll do</strong></p>
<ul><li>• Design evaluation sets</li><li>Ship LLM features</li></ul>
<h3>Benefits</h3><ul><li>Private healthcare</li><li>Gym</li></ul>
<p>We are an equal opportunity employer and value diversity.</p>
"""


def test_html_to_text_keeps_structure() -> None:
    text = html_to_text(POSTING_HTML)
    assert "## About the role" in text
    assert "## What you'll do" in text  # bold-only paragraph becomes a heading
    assert "- Design evaluation sets" in text  # bullet characters normalised
    assert "<" not in text


def test_strip_boilerplate_keeps_the_work_and_drops_the_rest() -> None:
    result = clean_posting(POSTING_HTML, None)
    assert "RAG pipelines" in result.role_text
    assert "Ship LLM features" in result.role_text
    for gone in ("widgets", "healthcare", "equal opportunity"):
        assert gone not in result.role_text
        assert gone in result.full_text or gone == "equal opportunity"
    assert result.dropped_headings == ("About Acme", "Benefits")


def test_plain_text_headings_are_recognised() -> None:
    text = "WHO ARE WE?\nWe make models.\n\nResponsibilities:\n- Build agents\n\nPERKS\nFree lunch"
    result = clean_posting(None, text)
    assert result.role_text == "Responsibilities:\n- Build agents"


@pytest.mark.parametrize(
    "heading",
    [
        "Why Acme?",
        "Our Recruitment Ethos",
        "Our Interview Process",
        "🔍 The Interview Process:",
        "Sponsorship",
        "More about Acme:",
        "Join the Team at Acme",
        "Our Global Structure",
        "Compliance",
        "How we work 💻- Locations & Flexible Working:",
        "The team and culture",
    ],
)
def test_real_world_boilerplate_headings(heading: str) -> None:
    # Heading styles seen in real UK AI postings on 2026-10-31.
    result = clean_posting(None, f"## Responsibilities\n- Build evals\n\n## {heading}\nNoise")
    assert result.dropped_headings == (heading.rstrip(":"),)


@pytest.mark.parametrize(
    "heading",
    ["About the team", "🧠 Your day-to-day", "What you'll be doing:", "In this role, you will:"],
)
def test_headings_about_the_work_are_kept(heading: str) -> None:
    result = clean_posting(None, f"## {heading}\n- Build evals")
    assert result.dropped_headings == ()


def test_content_hash_ignores_whitespace_noise() -> None:
    assert content_hash("a  b\n\n\n c") == content_hash("a b\n\nc")


@pytest.mark.parametrize(
    ("locations", "hints", "expected"),
    [
        (("London, UK",), (), True),
        (("Remote - United Kingdom",), (), True),
        (("Edinburgh",), (), True),
        ((), ("GB",), True),
        ((), ("United Kingdom",), True),
        (("London, Ontario",), (), False),
        (("London, ON",), (), False),
        (("Cambridge, MA",), (), False),
        (("New York",), (), False),
        (("Remote",), (), False),
        (("Barcelona", "Paris"), (), False),
        (("San Francisco, CA", "London"), (), True),  # any UK location counts
    ],
)
def test_in_country_uk(locations: tuple[str, ...], hints: tuple[str, ...], expected: bool) -> None:
    assert in_country(locations, hints, "GB") is expected


# Real postings run to hundreds of words; near-duplicate thresholds assume that length.
BODY = (
    "You will design retrieval augmented generation pipelines, build evaluation harnesses, "
    "work with product managers to ship LLM features, monitor latency and cost in production, "
    "and mentor engineers on prompt design and model selection across the platform team. "
    "In your first months you will own the document ingestion service, improve chunking and "
    "ranking, and set up offline evaluation so every change is measured before release. "
    "You will pair with designers on how answers are shown, write clear design documents, "
    "review pull requests from other engineers, and take part in a light on-call rotation. "
    "We use Python, FastAPI, Postgres with pgvector, and a mix of hosted and open models. "
    "You should have shipped software to production, be comfortable reading model outputs "
    "critically, and enjoy explaining trade-offs to people who are not engineers."
)


def _doc(
    doc_id: str,
    text: str,
    *,
    company: str = "Acme",
    title: str = "GenAI Engineer",
    full: bool = True,
    posted: date | None = date(2026, 10, 1),
) -> DedupDoc:
    return DedupDoc(doc_id, text, title, company, full, posted)


def test_near_duplicate_reposts_are_grouped() -> None:
    repost = BODY.replace("mentor engineers", "mentor junior engineers")
    result = find_duplicates(
        [
            _doc("a", BODY, posted=date(2026, 10, 5)),
            _doc("b", repost, company="Recruit Co", posted=date(2026, 10, 1)),
            _doc("c", "Kotlin Android engineer building payments screens for our mobile app."),
        ]
    )
    assert result.group_of["a"] == result.group_of["b"] == "b"  # earliest wins
    assert result.duplicates == {"a"}
    assert result.group_count == 2


def test_snippet_is_matched_to_its_full_posting_by_containment() -> None:
    snippet = BODY[:120]
    result = find_duplicates(
        [_doc("full", BODY), _doc("snip", snippet, full=False, posted=date(2026, 9, 1))]
    )
    assert result.group_of["snip"] == "full"  # full text beats an earlier snippet
    assert result.duplicates == {"snip"}


def test_snippet_from_a_different_job_is_kept() -> None:
    result = find_duplicates(
        [_doc("full", BODY), _doc("snip", BODY[:120], title="Data Engineer", full=False)]
    )
    assert result.duplicates == frozenset()


def test_distinct_postings_stay_separate() -> None:
    other = (
        "Own our agent orchestration layer: tool calling, memory, multi-agent coordination, "
        "guardrails and end to end evaluation of agent behaviour for enterprise customers."
    )
    result = find_duplicates([_doc("a", BODY), _doc("b", other)])
    assert result.group_count == 2
