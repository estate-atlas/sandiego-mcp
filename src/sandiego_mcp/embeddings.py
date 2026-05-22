"""Voyage AI embedding helper.

Matches the embedding model the warehouse is indexed with
(voyage-4-large, 1024 dims). Keeping this isolated so we can
swap providers without touching tool code.

Provider: Voyage AI (https://www.voyageai.com) — Anthropic's embedding partner.
Auth:     SANDIEGO_MCP_VOYAGE_API_KEY (falls through to VOYAGE_API_KEY).
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import voyageai  # noqa: F401 — type hint only; runtime import is lazy

# Namespaced env vars so we don't collide with consumer apps that may run
# Ollama embeddings against a different DB. Fall through to generic names
# only if our namespaced ones are absent.
EMBEDDING_MODEL = (
    os.getenv("SANDIEGO_MCP_EMBEDDING_MODEL")
    or "voyage-4-large"
)
EMBEDDING_DIM = int(
    os.getenv("SANDIEGO_MCP_EMBEDDING_DIM")
    or "1024"
)


@lru_cache(maxsize=1)
def _client():  # -> voyageai.Client
    try:
        import voyageai  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError(
            "voyageai package is required. Install it with: pip install voyageai"
        ) from exc
    key = (
        os.getenv("SANDIEGO_MCP_VOYAGE_API_KEY")
        or os.getenv("VOYAGE_API_KEY")
    )
    if not key:
        raise RuntimeError(
            "SANDIEGO_MCP_VOYAGE_API_KEY (or VOYAGE_API_KEY) required to "
            "compute query embeddings. Set it in your MCP server env."
        )
    return voyageai.Client(api_key=key)


def embed(text: str) -> list[float]:
    result = _client().embed(
        texts=[text],
        model=EMBEDDING_MODEL,
        input_type="query",
        output_dimension=EMBEDDING_DIM,
    )
    return result.embeddings[0]


def vector_literal(vec: list[float]) -> str:
    """Format a Python list as a pgvector literal string."""
    return "[" + ",".join(str(v) for v in vec) + "]"
