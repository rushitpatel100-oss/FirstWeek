"""The hand-labelled evaluation: the packaged labels, scoring and the stability check."""

import uuid
from datetime import date
from typing import Any

import pytest
from sqlalchemy import delete, text
from sqlalchemy.exc import OperationalError
from test_extract import fake_gateway

from firstweek_core.contracts import RoleMatch
from firstweek_core.db.models import JobPosting, PostingRoleMatch, Source
from firstweek_core.db.session import get_engine, session_scope
from firstweek_research import evaluate as ev
from firstweek_research.extract import CLASSIFIER_VERSION
from firstweek_research.roles import load_roles
from firstweek_research.store import seed_roles

ROLES = {"genai-engineer", "agentic-ai-engineer", "ai-software-engineer"}


def test_packaged_labels_are_complete_and_valid() -> None:
    labels = ev.load_labels()
    assert labels.version == 1 and len(labels.postings) >= 100
    assert len({p.url for p in labels.postings}) == len(labels.postings)
    for p in labels.postings:
        assert set(p.labels) == ROLES, p.url  # every posting judged for every role
        assert p.note, p.url  # every judgement says why
    values = {v for p in labels.postings for v in p.labels.values()}
    assert values == {"yes", "no", "unsure"}  # YAML booleans were turned back into words


def test_a_bare_yaml_yes_or_no_is_read_as_a_label() -> None:
    item = ev.LabelledPosting(
        url="u", company="c", title="t", labels={"genai-engineer": True, "x": False}
    )
    assert item.labels == {"genai-engineer": "yes", "x": "no"}


def test_scores_handle_empty_cells() -> None:
    score = ev.RoleScore("genai-engineer", tp=0, fp=2, fn=1, tn=3)
    assert score.precision == 0.0 and score.recall == 0.0 and score.f1 == 0.0
    assert ev.RoleScore("genai-engineer").agreement is None


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


def _posting(url: str, title: str) -> JobPosting:
    with session_scope() as session:
        source = Source(
            url=url,
            tier="posting",
            provider="greenhouse",
            content_hash=uuid.uuid4().hex,
            content="text",
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
            is_full_text=True,
            text="Build LLM features with retrieval and evals.",
        )
        session.add(posting)
        session.flush()
        session.expunge(posting)
        return posting


def _decide(posting: JobPosting, is_match: bool, confidence: float, *, stale: bool = False) -> None:
    role = load_roles()["genai-engineer"]
    with session_scope() as session:
        archetype_id = seed_roles(session, load_roles())["genai-engineer"]
        session.add(
            PostingRoleMatch(
                posting_id=posting.id,
                archetype_id=archetype_id,
                is_match=is_match,
                confidence=confidence,
                reason="model reason",
                classifier_version=CLASSIFIER_VERSION,
                definition_hash="0000000000000000" if stale else role.definition_hash,
                model="anthropic/claude-haiku-5-5",
            )
        )


def _labels(*rows: tuple[str, str]) -> ev.LabelSet:
    return ev.LabelSet(
        version=1,
        labelled_on=date(2026, 10, 31),
        postings=[
            ev.LabelledPosting(
                url=url,
                company="Acme",
                title=url,
                labels={"genai-engineer": label},
                note="label note",
            )
            for url, label in rows
        ],
    )


@pytest.mark.db
@pytest.mark.usefixtures("_db")
def test_evaluation_scores_stored_decisions_against_labels() -> None:
    _decide(_posting("https://x/tp", "A"), True, 0.9)  # labelled yes, counted
    _decide(_posting("https://x/fp", "B"), True, 0.8)  # labelled no, counted
    _decide(_posting("https://x/fn", "C"), True, 0.4)  # labelled yes, too unsure to count
    _decide(_posting("https://x/tn", "D"), False, 0.9)  # labelled no, not counted
    _decide(_posting("https://x/unsure", "E"), True, 0.7)  # unsure label: reported only
    _decide(_posting("https://x/stale", "G"), True, 0.9, stale=True)  # old definition
    labels = _labels(
        ("https://x/tp", "yes"),
        ("https://x/fp", "no"),
        ("https://x/fn", "yes"),
        ("https://x/tn", "no"),
        ("https://x/unsure", "unsure"),
        ("https://x/never-collected", "yes"),
        ("https://x/stale", "no"),
    )

    result = ev.evaluate(labels)
    genai = next(r for r in result.roles if r.role == "genai-engineer")
    assert (genai.tp, genai.fp, genai.fn, genai.tn) == (1, 1, 1, 1)
    assert genai.precision == genai.recall == genai.agreement == genai.f1 == 0.5
    assert genai.unsure == 1 and genai.unsure_counted == 1
    assert genai.missing == 2  # never collected, and only a stale decision
    assert sorted(d.url for d in genai.disagreements) == ["https://x/fn", "https://x/fp"]
    fp = next(d for d in genai.disagreements if d.url == "https://x/fp")
    assert fp.counted and fp.label == "no" and fp.reason == "model reason"
    other = next(r for r in result.roles if r.role == "agentic-ai-engineer")
    assert other.scored == 0  # these labels only cover GenAI Engineer


@pytest.mark.db
@pytest.mark.usefixtures("_db")
async def test_stability_reports_postings_whose_answer_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _decide(_posting("https://x/steady", "Steady"), True, 0.9)
    _decide(_posting("https://x/wobbly", "Wobbly"), True, 0.9)
    calls: dict[str, int] = {}

    async def fake_classify(_gw: Any, _role: Any, view: Any, **_: Any) -> tuple[RoleMatch, str]:
        calls[view.title] = calls.get(view.title, 0) + 1
        flip = view.title == "Wobbly" and calls[view.title] == 2
        match = RoleMatch(is_target_role=not flip, confidence=0.8, reason="r")
        return match, "anthropic/claude-haiku-5-5"

    monkeypatch.setattr(ev, "classify", fake_classify)
    labels = _labels(("https://x/steady", "yes"), ("https://x/wobbly", "yes"))
    runs = await ev.stability(fake_gateway(), repeats=2, budget_usd=1.0, labels=labels)

    genai = next(r for r in runs if r.role == "genai-engineer")
    assert genai.postings == 2
    assert [title for _, title, _ in genai.flipped] == ["Wobbly"]
    assert genai.flipped[0][2] == [True, True, False]  # stored answer, then the two repeats
    assert calls == {"Steady": 2, "Wobbly": 2}
