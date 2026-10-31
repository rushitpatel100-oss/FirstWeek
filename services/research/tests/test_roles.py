import pytest

from firstweek_research.roles import load_roles, normalize_title, resolve_role


def test_golden_roles_load_and_are_unreviewed_until_checked() -> None:
    roles = load_roles()
    assert set(roles) == {"genai-engineer", "ai-software-engineer", "agentic-ai-engineer"}
    assert all(r.trust_level == "golden" for r in roles.values())


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Senior Gen-AI Engineer (London, Hybrid)", "gen ai engineer"),
        ("Lead Agentic AI Engineer - Remote", "agentic ai engineer"),
        ("Staff Software Engineer, Machine Learning", "software engineer machine learning"),
        ("Graduate LLM Engineer II", "llm engineer"),
    ],
)
def test_normalize_title_strips_level_location_and_punctuation(title: str, expected: str) -> None:
    assert normalize_title(title) == expected


@pytest.mark.parametrize(
    ("title", "slug", "method"),
    [
        ("GenAI Engineer", "genai-engineer", "exact"),
        ("Senior Generative AI Engineer", "genai-engineer", "exact"),
        ("Lead Agentic AI Engineer", "agentic-ai-engineer", "exact"),
        ("Principal AI Software Engineer", "ai-software-engineer", "exact"),
        ("Generative AI Engineers", "genai-engineer", "fuzzy"),
        ("Agentic AI Enginer", "agentic-ai-engineer", "fuzzy"),
    ],
)
def test_resolves_known_titles(title: str, slug: str, method: str) -> None:
    result = resolve_role(title)
    assert result.slug == slug
    assert result.method == method


def test_generic_ai_engineer_is_not_a_genai_engineer() -> None:
    # Decided 2026-10-31: "AI Engineer" is a different, broader title than GenAI Engineer.
    # It is offered as a suggestion but never resolved silently.
    for title in ("AI Engineer", "Senior AI Engineer", "Applied AI Engineer"):
        result = resolve_role(title)
        assert not result.resolved, title
    assert resolve_role("AI Engineer, Generative AI").slug == "genai-engineer"
    assert resolve_role("Agentic AI Engineer").slug == "agentic-ai-engineer"


def test_unknown_title_is_not_forced_onto_a_role() -> None:
    result = resolve_role("Mechanical Design Engineer")
    assert not result.resolved
    assert result.method == "none"


def test_title_pre_filter_is_loose_but_not_everything() -> None:
    genai = load_roles()["genai-engineer"]
    assert genai.title_matches("Senior Software Engineer, LLM Platform")
    assert genai.title_matches("Generative AI Developer")
    assert not genai.title_matches("Android Engineer")
    assert not genai.title_matches("Account Executive")
