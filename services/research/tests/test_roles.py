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


@pytest.mark.parametrize(
    "title",
    [
        # Missed by the old per-role patterns (evaluation, 2026-10-31).
        "Senior Software Engineer, GenAI Platform",
        "Senior GenAI Engineer (UK)",
        "Staff Software Engineer, Agentic Platform",
        "Senior Software Engineer \u2014 Infra Agent Systems UK",
        "Software Engineer, Codex Core Agents",
        "Staff Data Engineer \u2013 Agentic Applications",
    ],
)
def test_every_golden_role_shares_the_broad_ai_title_filter(title: str) -> None:
    roles = load_roles()
    assert {r.title_filter for r in roles.values()} == {"ai"}
    assert all(r.title_matches(title) for r in roles.values()), title


def test_shared_rule_on_building_roles_is_in_every_definition() -> None:
    # Decided 2026-10-31: managers, advisers and vendor customer-delivery roles never count.
    for role in load_roles().values():
        text = " ".join(role.definition.split())
        assert "Counts only when hands-on building is the main job." in text, role.slug
        assert "consultancy do count" in text, role.slug


def test_a_role_needs_a_title_filter() -> None:
    from pydantic import ValidationError

    from firstweek_research.roles import RoleDefinition

    base = {
        "slug": "x-engineer",
        "name": "X Engineer",
        "trust_level": "on_demand",
        "definition": "Builds X systems for production use across the whole company.",
        "aliases": ["X Engineer"],
    }
    with pytest.raises(ValidationError, match="title_filter or title_patterns"):
        RoleDefinition.model_validate(base)
    with pytest.raises(ValidationError, match="unknown title_filter"):
        RoleDefinition.model_validate({**base, "title_filter": "nope"})
    own = RoleDefinition.model_validate({**base, "title_patterns": [r"\bx engineer\b"]})
    assert own.title_matches("Senior X Engineer") and not own.title_matches("Senior AI Engineer")
