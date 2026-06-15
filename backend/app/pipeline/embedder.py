from __future__ import annotations

import os

import numpy as np
from google import genai
from google.genai import types

EMBED_MODEL = "models/text-embedding-004"
_BATCH_SIZE = 100


class Embedder:
    def __init__(self, api_key: str | None = None):
        key = api_key or os.environ["GOOGLE_API_KEY"]
        self._client = genai.Client(api_key=key)

    def embed_one(self, text: str, task_type: str = "RETRIEVAL_QUERY") -> np.ndarray:
        resp = self._client.models.embed_content(
            model=EMBED_MODEL,
            contents=text,
            config=types.EmbedContentConfig(task_type=task_type),
        )
        return np.array(resp.embeddings[0].values, dtype=np.float32)

    def embed_batch(
        self, texts: list[str], task_type: str = "RETRIEVAL_DOCUMENT"
    ) -> np.ndarray:
        vectors: list[list[float]] = []
        for i in range(0, len(texts), _BATCH_SIZE):
            chunk = texts[i : i + _BATCH_SIZE]
            resp = self._client.models.embed_content(
                model=EMBED_MODEL,
                contents=chunk,
                config=types.EmbedContentConfig(task_type=task_type),
            )
            vectors.extend(e.values for e in resp.embeddings)
        return np.array(vectors, dtype=np.float32)


def cosine_similarity(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """query: (D,), matrix: (N, D) → scores: (N,)"""
    q = query / (np.linalg.norm(query) + 1e-9)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-9
    return (matrix / norms) @ q
