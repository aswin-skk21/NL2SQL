from __future__ import annotations

import pandas as pd

from ..config import CONNECT_TIMEOUT, MAX_ROWS, QUERY_TIMEOUT, resolve_conn_str
from ..models import ExecutionResult, ValidationResult


def execute_sql(result: ValidationResult, server: str, database: str) -> ExecutionResult:
    """Run validated SELECT SQL and return at most MAX_ROWS rows.

    Blocking by design — callers on an event loop must dispatch this to a
    worker thread (FastAPI does that automatically for `def` endpoints).
    """
    if not result.is_valid:
        raise ValueError(
            f"Cannot execute invalid SQL after {result.attempts} attempt(s): "
            f"{result.error_message}"
        )

    import pyodbc

    conn_str = resolve_conn_str(server, database)

    with pyodbc.connect(conn_str, timeout=CONNECT_TIMEOUT) as conn:
        # Statement timeout — without it a runaway query pins the server.
        conn.timeout = QUERY_TIMEOUT
        cursor = conn.cursor()
        cursor.execute(result.sql)
        columns = [d[0] for d in cursor.description] if cursor.description else []
        # Fetch one extra row so we can tell "exactly MAX_ROWS" from "truncated".
        fetched = cursor.fetchmany(MAX_ROWS + 1)

    truncated = len(fetched) > MAX_ROWS
    rows = fetched[:MAX_ROWS]
    df = pd.DataFrame.from_records([tuple(r) for r in rows], columns=columns)

    return ExecutionResult(
        df=df,
        row_count=len(df),
        sql_executed=result.sql,
        truncated=truncated,
    )
