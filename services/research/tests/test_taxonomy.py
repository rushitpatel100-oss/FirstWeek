from types import SimpleNamespace

import pytest

from firstweek_research.taxonomy import load_taxonomy, normalize_term


def test_taxonomy_loads_with_unique_names() -> None:
    taxonomy = load_taxonomy()
    assert len(taxonomy.entries) >= 100
    assert "Python" in taxonomy.vocabulary("tool")
    assert "RAG" in taxonomy.vocabulary("skill")


def test_normalize_term() -> None:
    assert normalize_term("Retrieval-Augmented Generation") == "retrieval augmented generation"
    assert normalize_term("Next.js") == "next.js"
    assert normalize_term("C++") == "c++"
    assert normalize_term("Weights & Biases") == "weights and biases"


@pytest.mark.parametrize(
    ("label", "slug"),
    [
        ("RAG", "rag"),
        ("retrieval augmented generation", "rag"),
        ("RAG (retrieval-augmented generation)", "rag"),
        ("LangGraph", "langgraph"),
        ("Pytorh", "pytorch"),  # typo within the fuzzy margin
        ("Fine tuning", "fine-tuning"),
        ("function calling", "tool-calling"),
        ("Golang", "go"),
        ("GO", "go"),
        ("Pinecone", "vector-databases"),
        ("evals", "llm-evaluation"),
    ],
)
def test_lookup_maps_known_terms(label: str, slug: str) -> None:
    assert load_taxonomy().lookup(label) == slug


@pytest.mark.parametrize(
    "label",
    [
        "Git2",  # short names never fuzzy-match
        "Quantum chemistry",
        "Excellent attention to detail",
        "",
    ],
)
def test_lookup_leaves_unknown_terms_unmapped(label: str) -> None:
    assert load_taxonomy().lookup(label) is None


# ---------------------------------------------------------------------- ESCO links


def test_esco_links_are_valid_unique_and_only_true_equivalents() -> None:
    entries = load_taxonomy().entries
    linked = {slug for slug, e in entries.items() if e.esco_uri}
    # Chosen by hand on 2026-10-31 from `make esco-suggest`; AI-specific entries stay unlinked.
    assert {"machine-learning", "python", "sql", "postgres", "system-design"} <= linked
    assert not linked & {"rag", "prompt-engineering", "ai-agents", "llm-evaluation", "mlops"}
    assert len({entries[s].esco_uri for s in linked}) == len(linked)


def test_bad_or_duplicate_esco_links_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic import ValidationError

    from firstweek_research import taxonomy

    with pytest.raises(ValidationError):
        taxonomy.SkillEntry(slug="x", label="X", kind="skill", esco_uri="http://example.com/x")
    uri = "http://data.europa.eu/esco/skill/3a2d5b45-56e4-4f5a-a55a-4a4a65afdc43"
    twice = (
        "skills:\n"
        f"  - {{slug: a, label: A, kind: skill, esco_uri: {uri}}}\n"
        f"  - {{slug: b, label: B, kind: skill, esco_uri: {uri}}}\n"
    )

    class FakeFile:
        def read_text(self, _: str) -> str:
            return twice

    class FakeDir:
        def __truediv__(self, _: str) -> "FakeDir | FakeFile":
            return FakeFile() if _ == "ai_skills.yaml" else FakeDir()

    monkeypatch.setattr(
        "firstweek_research.taxonomy.resources", SimpleNamespace(files=lambda _: FakeDir())
    )
    taxonomy.load_taxonomy.cache_clear()
    try:
        with pytest.raises(ValueError, match="same ESCO skill"):
            taxonomy.load_taxonomy()
    finally:
        taxonomy.load_taxonomy.cache_clear()


async def test_esco_suggestions_put_same_name_matches_first() -> None:
    import httpx

    from firstweek_research.esco import suggest
    from firstweek_research.taxonomy import SkillEntry

    def skill(uuid_tail: str, title: str) -> dict[str, str]:
        return {
            "uri": f"http://data.europa.eu/esco/skill/00000000-0000-0000-0000-{uuid_tail}",
            "title": title,
            "searchHit": f"About {title}.",
        }

    pages = {
        "Machine learning": [
            skill("000000000001", "data mining"),
            skill("000000000002", "machine learning"),
        ],
        "ML": [
            skill("000000000002", "machine learning"),
            skill("000000000003", "ML (computer programming)"),
        ],
    }
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        text = request.url.params["text"]
        requests.append(text)
        assert request.url.params["selectedVersion"] == "v1.2.0"
        if text not in pages:
            return httpx.Response(404)
        return httpx.Response(200, json={"_embedded": {"results": pages[text]}})

    entry = SkillEntry(
        slug="machine-learning",
        label="Machine learning",
        kind="skill",
        aliases=["ML", "applied machine learning"],
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        found = await suggest(client, entry)

    assert requests == ["Machine learning", "ML", "applied machine learning"]
    assert [f.label for f in found] == [
        "machine learning",
        "data mining",
        "ML (computer programming)",
    ]
    assert found[0].same_name_as(entry) and not found[1].same_name_as(entry)
