"""
Embedding helper: calls Ollama to produce vectors for Qdrant upserts.

The output dimension must match qdrant_vector_size in settings (4096 for
llama3.2).  Embeddings are fetched via the Ollama REST API on the Windows
host (http://172.17.0.1:11434).
"""
from __future__ import annotations

import logging

import httpx

from shared.config import settings

logger = logging.getLogger(__name__)

_EMBED_ENDPOINT = "/api/embeddings"


async def embed(text: str) -> list[float]:
    """Return a single embedding vector for `text`."""
    url = settings.ollama_base_url.rstrip("/") + _EMBED_ENDPOINT
    async with httpx.AsyncClient(timeout=settings.ollama_timeout_s) as client:
        resp = await client.post(
            url,
            json={"model": settings.ollama_model, "prompt": text},
        )
        resp.raise_for_status()
    data = resp.json()
    vec: list[float] = data["embedding"]
    if len(vec) != settings.qdrant_vector_size:
        logger.warning(
            "embedding dim mismatch: got %d, expected %d",
            len(vec),
            settings.qdrant_vector_size,
        )
    return vec


async def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts sequentially (Ollama has no native batch endpoint)."""
    results = []
    for text in texts:
        results.append(await embed(text))
    return results
