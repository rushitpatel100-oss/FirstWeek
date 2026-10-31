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
