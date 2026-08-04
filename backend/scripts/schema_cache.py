"""Offline schema introspection — run once per environment to build the cache.

Usage:
    python schema_cache.py
"""

from __future__ import annotations

import json
import pathlib
import sys
import warnings
from datetime import datetime, timezone

# Make backend/ importable regardless of which directory this is run from
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import numpy as np

import env_loader
env_loader.load()

from app.config import SERVERS, build_odbc_conn_str
from app.pipeline.embedder import EMBED_DIM, Embedder
from app.models import ColumnInfo, SchemaCache, TableInfo

CACHE_PATH = pathlib.Path(__file__).parent / "schema_cache.json"
EMBED_PATH = pathlib.Path(__file__).parent / "schema_embeddings.npy"
PROGRESS_PATH = pathlib.Path(__file__).parent / "schema_embeddings.progress.json"

_TABLES_SQL = """
SELECT
    t.TABLE_CATALOG  AS database_name,
    t.TABLE_SCHEMA   AS schema_name,
    t.TABLE_NAME     AS table_name
FROM INFORMATION_SCHEMA.TABLES t
WHERE t.TABLE_TYPE = 'BASE TABLE'
ORDER BY t.TABLE_SCHEMA, t.TABLE_NAME;
"""

_COLUMNS_SQL = """
SELECT
    c.TABLE_SCHEMA              AS schema_name,
    c.TABLE_NAME                AS table_name,
    c.COLUMN_NAME               AS column_name,
    c.DATA_TYPE                 AS data_type,
    c.IS_NULLABLE               AS is_nullable,
    c.CHARACTER_MAXIMUM_LENGTH  AS max_length
FROM INFORMATION_SCHEMA.COLUMNS c
WHERE c.TABLE_NAME IN (
    SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = 'BASE TABLE'
)
ORDER BY c.TABLE_SCHEMA, c.TABLE_NAME, c.ORDINAL_POSITION;
"""

_ROW_COUNTS_SQL = """
SELECT
    s.name  AS schema_name,
    t.name  AS table_name,
    p.rows  AS row_count_estimate
FROM sys.tables t
JOIN sys.schemas s    ON t.schema_id = s.schema_id
JOIN sys.partitions p ON t.object_id = p.object_id
WHERE p.index_id IN (0, 1);
"""


def _introspect_database(server_alias: str, database: str) -> list[TableInfo]:
    import pyodbc

    cfg = SERVERS[server_alias]
    conn_str = build_odbc_conn_str(cfg, database)
    try:
        with pyodbc.connect(conn_str, autocommit=True, timeout=15) as conn:
            cursor = conn.cursor()

            cursor.execute(_TABLES_SQL)
            table_rows = cursor.fetchall()

            cursor.execute(_COLUMNS_SQL)
            col_rows = cursor.fetchall()

            cursor.execute(_ROW_COUNTS_SQL)
            count_rows = cursor.fetchall()
    except Exception as exc:
        warnings.warn(f"[schema_cache] skipping {server_alias}.{database}: {exc}")
        return []

    col_map: dict[tuple[str, str], list[ColumnInfo]] = {}
    for row in col_rows:
        key = (row.schema_name, row.table_name)
        col_map.setdefault(key, []).append(
            ColumnInfo(
                name=row.column_name,
                data_type=row.data_type,
                is_nullable=(row.is_nullable == "YES"),
                max_length=row.max_length,
            )
        )

    count_map: dict[tuple[str, str], int] = {
        (r.schema_name, r.table_name): r.row_count_estimate for r in count_rows
    }

    tables: list[TableInfo] = []
    for row in table_rows:
        key = (row.schema_name, row.table_name)
        t = TableInfo(
            server=server_alias,
            database=database,
            schema=row.schema_name,
            table=row.table_name,
            columns=col_map.get(key, []),
            row_count_estimate=count_map.get(key),
        )
        t.embedding_token = _make_token(t)
        tables.append(t)

    return tables


def _make_token(t: TableInfo) -> str:
    cols = ", ".join(f"{c.name}({c.data_type})" for c in t.columns)
    return f"{t.server}.{t.database}.{t.schema}.{t.table}: {cols}"


def build_cache(servers: dict | None = None) -> SchemaCache:
    if servers is None:
        servers = SERVERS
    all_tables: list[TableInfo] = []
    for alias, cfg in servers.items():
        for db in cfg.databases:
            print(f"  introspecting {alias}.{db} …")
            tables = _introspect_database(alias, db)
            print(f"    → {len(tables)} tables")
            all_tables.extend(tables)
    return SchemaCache(
        tables=all_tables,
        built_at=datetime.now(timezone.utc).isoformat(),
    )


def _write_table_json(cache: SchemaCache) -> None:
    data = {
        "built_at": cache.built_at,
        "tables": [
            {
                "server": t.server,
                "database": t.database,
                "schema": t.schema,
                "table": t.table,
                "row_count_estimate": t.row_count_estimate,
                "embedding_token": t.embedding_token,
                "columns": [
                    {
                        "name": c.name,
                        "data_type": c.data_type,
                        "is_nullable": c.is_nullable,
                        "max_length": c.max_length,
                        "description": c.description,
                    }
                    for c in t.columns
                ],
            }
            for t in cache.tables
        ],
    }
    CACHE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _load_partial_embeddings(expected_tokens: list[str]) -> np.ndarray | None:
    """Return a partial embeddings matrix from a prior run, or None if there's
    nothing usable to resume from (mismatched table set, no progress file)."""
    if not EMBED_PATH.exists() or not PROGRESS_PATH.exists():
        return None
    progress = json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
    if progress.get("tokens") != expected_tokens[: len(progress.get("tokens", []))]:
        return None  # table order/content changed since the last partial run
    matrix = np.load(EMBED_PATH)
    if matrix.shape[0] != len(progress.get("tokens", [])):
        return None
    return matrix


def save_cache(
    cache: SchemaCache, embedder: Embedder, chunk_tables: int | None = None
) -> bool:
    """Write schema_cache.json, then embed tables in resumable chunks.

    Returns True once every table has an embedding, False if a `chunk_tables`
    limit stopped the run partway — re-run the script to continue.
    """
    _write_table_json(cache)

    if not cache.tables:
        np.save(EMBED_PATH, np.empty((0, EMBED_DIM), dtype=np.float32))
        PROGRESS_PATH.unlink(missing_ok=True)
        print(f"Saved {CACHE_PATH} and {EMBED_PATH}")
        return True

    tokens = [t.embedding_token for t in cache.tables]
    done_matrix = _load_partial_embeddings(tokens)
    start = done_matrix.shape[0] if done_matrix is not None else 0

    remaining = tokens[start:]
    if chunk_tables is not None:
        remaining = remaining[:chunk_tables]

    if not remaining:
        print(f"  all {len(tokens)} tables already embedded.")
    else:
        end = start + len(remaining)
        print(f"  embedding tables {start + 1}-{end} of {len(tokens)} …")
        new_matrix = embedder.embed_batch(remaining, task_type="RETRIEVAL_DOCUMENT")
        done_matrix = (
            new_matrix
            if done_matrix is None
            else np.concatenate([done_matrix, new_matrix], axis=0)
        )
        np.save(EMBED_PATH, done_matrix)
        PROGRESS_PATH.write_text(
            json.dumps({"tokens": tokens[: done_matrix.shape[0]]}), encoding="utf-8"
        )

    finished = done_matrix is not None and done_matrix.shape[0] >= len(tokens)
    if finished:
        PROGRESS_PATH.unlink(missing_ok=True)
        print(f"Saved {CACHE_PATH} and {EMBED_PATH} — {len(tokens)}/{len(tokens)} embedded.")
    else:
        print(
            f"Partial progress saved: {done_matrix.shape[0]}/{len(tokens)} embedded. "
            "Re-run this script to continue."
        )
    return finished


def load_cache() -> SchemaCache:
    data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    tables = []
    for td in data["tables"]:
        columns = [
            ColumnInfo(
                name=c["name"],
                data_type=c["data_type"],
                is_nullable=c["is_nullable"],
                max_length=c["max_length"],
                description=c.get("description", ""),
            )
            for c in td["columns"]
        ]
        tables.append(
            TableInfo(
                server=td["server"],
                database=td["database"],
                schema=td["schema"],
                table=td["table"],
                columns=columns,
                row_count_estimate=td.get("row_count_estimate"),
                embedding_token=td["embedding_token"],
            )
        )
    return SchemaCache(tables=tables, built_at=data.get("built_at", ""))


def load_embeddings() -> np.ndarray:
    return np.load(EMBED_PATH)


if __name__ == "__main__":
    import argparse
    import os

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--chunk-tables",
        type=int,
        default=None,
        help="Embed at most this many tables this run, then save progress and "
        "exit (0). Re-run to continue from where it left off. Omit to embed "
        "everything in one run.",
    )
    args = parser.parse_args()

    embedder = Embedder(api_key=os.environ["GOOGLE_API_KEY"])

    if CACHE_PATH.exists():
        print("Reusing existing schema_cache.json (delete it to force re-introspection).")
        cache = load_cache()
    else:
        print("Building schema cache …")
        cache = build_cache()

    print(f"Total tables: {len(cache.tables)}")
    finished = save_cache(cache, embedder, chunk_tables=args.chunk_tables)
    sys.exit(0 if finished else 3)
