from __future__ import annotations

import numpy as np
from fastembed import TextEmbedding

# Local, offline embedding model — no external API calls, no quota/rate limits.
# Gemini is still used elsewhere in the pipeline (routing, SQL generation,
# answering); only the vector-similarity step runs locally.
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
EMBED_DIM = 384

# BGE models are asymmetric: queries need an instruction prefix, documents don't.
_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class Embedder:
    _model: TextEmbedding | None = None

    def __init__(self, api_key: str | None = None):
        # api_key is accepted (unused) to keep call sites unchanged — the local
        # model needs no credentials.
        if Embedder._model is None:
            Embedder._model = TextEmbedding(model_name=EMBED_MODEL)

    def embed_one(self, text: str, task_type: str = "RETRIEVAL_QUERY") -> np.ndarray:
        if task_type == "RETRIEVAL_QUERY":
            text = _QUERY_PREFIX + text
        vec = next(self._model.embed([text]))
        return np.array(vec, dtype=np.float32)

    def embed_batch(
        self, texts: list[str], task_type: str = "RETRIEVAL_DOCUMENT"
    ) -> np.ndarray:
        if task_type == "RETRIEVAL_QUERY":
            texts = [_QUERY_PREFIX + t for t in texts]
        vectors = list(self._model.embed(texts))
        return np.array(vectors, dtype=np.float32)


def cosine_similarity(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """query: (D,), matrix: (N, D) → scores: (N,)"""
    q = query / (np.linalg.norm(query) + 1e-9)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-9
    return (matrix / norms) @ q
