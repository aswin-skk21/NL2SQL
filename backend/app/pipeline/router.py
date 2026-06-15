from __future__ import annotations

import json

import numpy as np
from google import genai
from google.genai import types

from .embedder import Embedder, cosine_similarity
from ..models import SchemaCache, SchemaContext, TableInfo
from ..prompts import ROUTER_SYSTEM, ROUTER_USER

_SIMILARITY_THRESHOLD = 0.35
_MAX_CANDIDATES = 25
_ROUTER_MODEL = "gemini-2.5-flash"


def route(
    question: str,
    cache: SchemaCache,
    table_embeddings: np.ndarray,
    embedder: Embedder,
    llm_client: genai.Client,
) -> SchemaContext:
    if not cache.tables:
        raise RuntimeError(
            "Schema cache is empty. Run schema_cache.py first and populate "
            "databases in config.py."
        )

    question_vec = embedder.embed_one(question, task_type="RETRIEVAL_QUERY")
    scores = cosine_similarity(question_vec, table_embeddings)

    indexed = sorted(
        enumerate(scores.tolist()), key=lambda x: x[1], reverse=True
    )
    candidates: list[tuple[TableInfo, float]] = [
        (cache.tables[i], s)
        for i, s in indexed
        if s >= _SIMILARITY_THRESHOLD
    ][:_MAX_CANDIDATES]

    if not candidates:
        # Fall back to top-5 regardless of threshold
        candidates = [(cache.tables[i], s) for i, s in indexed[:5]]

    candidate_block = _format_candidates(candidates)
    server, database, table_names = _llm_route(
        question, candidate_block, llm_client
    )

    selected_tables = _resolve_tables(server, database, table_names, cache)

    return SchemaContext(
        question=question,
        relevant_tables=selected_tables,
        server=server,
        database=database,
    )


def _format_candidates(candidates: list[tuple[TableInfo, float]]) -> str:
    lines = []
    for t, score in candidates:
        col_str = ", ".join(
            f"{c.name} ({c.data_type})" for c in t.columns[:20]
        )
        lines.append(
            f"[{score:.2f}] {t.server} / {t.database} / {t.schema}.{t.table}\n"
            f"  Columns: {col_str}"
        )
    return "\n\n".join(lines)


def _llm_route(
    question: str,
    candidate_block: str,
    llm_client: genai.Client,
) -> tuple[str, str, list[str]]:
    prompt = ROUTER_USER.format(question=question, candidate_block=candidate_block)
    resp = llm_client.models.generate_content(
        model=_ROUTER_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=ROUTER_SYSTEM,
            temperature=0.0,
            response_mime_type="application/json",
        ),
    )
    raw = resp.text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    data = json.loads(raw)
    server = data.get("server", "")
    database = data.get("database", "")
    tables = data.get("tables", [])
    return server, database, tables


def _resolve_tables(
    server: str,
    database: str,
    table_names: list[str],
    cache: SchemaCache,
) -> list[TableInfo]:
    lookup: dict[str, TableInfo] = {}
    for t in cache.tables:
        if t.server == server and t.database == database:
            lookup[f"{t.schema}.{t.table}"] = t
            lookup[t.table] = t

    resolved = []
    for name in table_names:
        if name in lookup:
            resolved.append(lookup[name])
    return resolved
