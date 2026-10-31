"""Free, local text embeddings (ADR 0012), used through LLMGateway.embed.

fastembed runs small open-source models with ONNX Runtime on the CPU: no API key, no cost,
no PyTorch. It ships with firstweek-research (the services that embed), not with core, so
it is imported only when an embedding is actually requested.
"""

import os
from functools import cache
from typing import Any, Literal

EmbedKind = Literal["passage", "query"]

# English BGE models find passages better when a short search query starts with this
# instruction (BAAI's model card); passages are embedded as they are. fastembed does not
# add it, so it is added here.
BGE_QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


def query_prefix(name: str) -> str:
    return BGE_QUERY_INSTRUCTION if name.startswith("BAAI/bge-") and "-en" in name else ""


@cache
def _model(name: str, cache_dir: str) -> Any:
    try:
        from fastembed import TextEmbedding
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise RuntimeError(
            "Local embeddings need the fastembed package (part of firstweek-research). "
            "Install it with: uv sync --all-packages"
        ) from exc
    return TextEmbedding(name, cache_dir=os.path.expanduser(cache_dir))


def embed_local(name: str, texts: list[str], kind: EmbedKind, cache_dir: str) -> list[list[float]]:
    """Unit-length vectors, one per text."""
    if kind == "query":
        texts = [query_prefix(name) + t for t in texts]
    return [[float(x) for x in v] for v in _model(name, cache_dir).embed(texts)]
