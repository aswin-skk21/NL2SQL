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
from app.pipeline.embedder import Embedder
from app.models import ColumnInfo, SchemaCache, TableInfo

CACHE_PATH = pathlib.Path(__file__).parent / "schema_cache.json"
EMBED_PATH = pathlib.Path(__file__).parent / "schema_embeddings.npy"

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


def save_cache(cache: SchemaCache, embedder: Embedder) -> None:
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

    if cache.tables:
        print(f"  embedding {len(cache.tables)} tables …")
        tokens = [t.embedding_token for t in cache.tables]
        matrix = embedder.embed_batch(tokens, task_type="RETRIEVAL_DOCUMENT")
        np.save(EMBED_PATH, matrix)
    else:
        np.save(EMBED_PATH, np.empty((0, 768), dtype=np.float32))

    print(f"Saved {CACHE_PATH} and {EMBED_PATH}")


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
    import os

    embedder = Embedder(api_key=os.environ["GOOGLE_API_KEY"])
    print("Building schema cache …")
    cache = build_cache()
    print(f"Total tables: {len(cache.tables)}")
    save_cache(cache, embedder)
