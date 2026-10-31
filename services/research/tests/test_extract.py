import json
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from firstweek_core.config import Settings
from firstweek_core.contracts import ExtractedItem, PostingExtraction
from firstweek_core.llm import BudgetRegistry, LLMGateway
from firstweek_core.llm.tracing import NoopTracer
from firstweek_research.extract import (
    CLASSIFIER_VERSION,
    EXTRACTOR_VERSION,
    PostingView,
    classify,
    extract,
    load_prompt,
    quote_in_text,
    verify,
)
from firstweek_research.roles import load_roles
from firstweek_research.stats import wilson_interval
from firstweek_research.taxonomy import load_taxonomy

TEXT = (
    "## About the role\nYou\u2019ll build RAG pipelines in Python and design evaluation sets.\n"
    "- Own our LangGraph agents\n- Work with product managers on roadmaps"
)


def item(label: str, quote: str) -> ExtractedItem:
    return ExtractedItem(label=label, quote=quote)


@pytest.mark.parametrize(
    ("quote", "found"),
    [
        ("You'll build RAG pipelines in Python", True),  # straight vs curly apostrophe
        ("build  RAG\npipelines", True),  # whitespace differences
        ("BUILD RAG PIPELINES", True),  # case
        ("Own our LangGraph agents.", True),  # trailing punctuation
        ("build retrieval pipelines in Python", False),  # paraphrase
        ("Kubernetes experience required", False),  # invented
        ("RA", False),  # too short to mean anything
    ],
)
def test_quote_in_text(quote: str, found: bool) -> None:
    assert quote_in_text(quote, TEXT) is found


def test_verify_drops_unsupported_items_and_maps_the_taxonomy() -> None:
    extraction = PostingExtraction(
        seniority="mid",
        skills=[
            item("RAG", "build RAG pipelines"),
            item("Python", "RAG pipelines in Python"),  # a tool listed as a skill
            item("Retrieval-augmented generation", "You\u2019ll build RAG pipelines"),  # duplicate
            item("Kubernetes", "Kubernetes experience required"),  # not in the text
        ],
        tools=[item("LangGraph", "Own our LangGraph agents")],
        responsibilities=[item("Design evaluation sets", "design evaluation sets")],
    )
    kept, dropped = verify(extraction, TEXT, load_taxonomy())
    assert [(k.kind, k.skill_slug) for k in kept] == [
        ("skill", "rag"),
        ("tool", "python"),  # the taxonomy corrects the kind
        ("tool", "langgraph"),
        ("responsibility", None),
    ]
    assert [d[1].label for d in dropped] == ["Kubernetes"]


def test_prompts_have_system_and_user_parts() -> None:
    for version in (CLASSIFIER_VERSION, EXTRACTOR_VERSION):
        system, user = load_prompt(version)
        assert system and user and "{text}" in user


@pytest.mark.parametrize(
    ("k", "n", "low", "high"),
    [
        (0, 10, 0.0, 0.2775),
        (5, 10, 0.2366, 0.7634),
        (10, 10, 0.7225, 1.0),
        (60, 100, 0.502, 0.6906),
    ],
)
def test_wilson_interval(k: int, n: int, low: float, high: float) -> None:
    lo, hi = wilson_interval(k, n)
    assert lo == pytest.approx(low, abs=1e-3)
    assert hi == pytest.approx(high, abs=1e-3)


def test_wilson_interval_empty_sample_is_fully_uncertain() -> None:
    assert wilson_interval(0, 0) == (0.0, 1.0)


# ------------------------------------------------------------- with a fake model


def fake_llm_reply(**kwargs: Any) -> str:
    """Answers in the contract's shape, using only words that are in the posting,
    plus one invented quote per extraction so verification has something to catch."""
    schema = kwargs["response_format"]["json_schema"]["name"]
    user = kwargs["messages"][-1]["content"]
    text = user.split("<<<", 1)[-1]
    if schema == "RoleMatch":
        hit = any(w in text for w in ("RAG", "agents", "LLM"))
        return json.dumps(
            {"is_target_role": hit, "confidence": 0.9 if hit else 0.8, "reason": "Test reason."}
        )
    words = text.replace("\n", " ").split()
    window = " ".join(words[2:8])
    return json.dumps(
        {
            "seniority": "senior",
            "skills": [
                {"label": "RAG", "quote": window}
                if "RAG" in text
                else {"label": "Python", "quote": window},
                {"label": "Kubernetes", "quote": "Invented: deep Kubernetes expertise required"},
            ],
            "tools": [{"label": "Python", "quote": window}],
            "responsibilities": [{"label": "Build features", "quote": window}],
        }
    )


def fake_gateway(budget: str = "5") -> LLMGateway:
    async def completion(**kwargs: Any) -> SimpleNamespace:
        content = fake_llm_reply(**kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=SimpleNamespace(prompt_tokens=2000, completion_tokens=300),
        )

    return LLMGateway(
        settings=Settings(_env_file=None),
        completion_fn=completion,
        tracer=NoopTracer(),
        budgets=BudgetRegistry(Decimal(budget)),
    )


POSTING = PostingView("p1", "s1", "Senior GenAI Engineer", "Acme", TEXT)


async def test_classify_returns_a_validated_match() -> None:
    match, model = await classify(
        fake_gateway(), load_roles()["genai-engineer"], POSTING, budget_scope="t"
    )
    assert match.is_target_role and match.confidence == 0.9
    assert model == "anthropic/claude-haiku-5-5"  # classification uses the small tier


async def test_extract_verifies_quotes_and_counts_the_invented_one() -> None:
    outcome = await extract(fake_gateway(), POSTING, load_taxonomy(), budget_scope="t")
    assert outcome.seniority == "senior"
    assert outcome.model == "anthropic/claude-sonnet-5-5"  # extraction uses the mid tier
    assert [d[1].label for d in outcome.dropped] == ["Kubernetes"]
    assert {i.skill_slug for i in outcome.items} >= {"rag", "python"}


@pytest.mark.parametrize(
    "tier_model", ["anthropic/claude-haiku-5-5", "anthropic/claude-sonnet-5-5"]
)
async def test_prompts_pass_litellm_parameter_checks(
    tier_model: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real LiteLLM request preparation (mock mode, no network) for both research prompts."""
    import functools

    import litellm

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    reply = json.dumps(
        {"is_target_role": True, "confidence": 0.7, "reason": "x"}
        if tier_model.endswith("haiku-5-5")
        else {"seniority": None, "skills": [], "tools": [], "responsibilities": []}
    )
    gateway = LLMGateway(
        settings=Settings(_env_file=None),
        completion_fn=functools.partial(litellm.acompletion, mock_response=reply),
        tracer=NoopTracer(),
        budgets=BudgetRegistry(Decimal("1")),
    )
    if tier_model.endswith("haiku-5-5"):
        match, _ = await classify(
            gateway, load_roles()["genai-engineer"], POSTING, budget_scope="t"
        )
        assert match.confidence == 0.7
    else:
        outcome = await extract(gateway, POSTING, load_taxonomy(), budget_scope="t")
        assert outcome.items == []
