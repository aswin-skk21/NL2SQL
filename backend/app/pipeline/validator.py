from __future__ import annotations

import sqlparse
from google import genai
from google.genai import types

from ..config import SERVERS, build_odbc_conn_str
from ..models import GeneratedSQL, SchemaContext, ValidationResult
from ..prompts import SQL_CORRECT_SYSTEM, SQL_CORRECT_USER
from .sql_generator import _format_schema_block, extract_sql_from_response

_MAX_RETRIES = 3
_CORRECT_MODEL = "gemini-2.5-pro"

_FORBIDDEN = {"drop", "insert", "update", "delete", "truncate", "exec", "execute", "xp_"}


def validate_and_correct(
    generated: GeneratedSQL,
    context: SchemaContext,
    llm_client: genai.Client,
    temperature: float = 0.1,
) -> ValidationResult:
    sql = generated.sql
    schema_block = _format_schema_block(context.relevant_tables)

    for attempt in range(1, _MAX_RETRIES + 1):
        guard_err = _sqlparse_guard(sql)
        if guard_err:
            if attempt < _MAX_RETRIES:
                sql = _llm_correct(sql, guard_err, context, schema_block, llm_client, temperature)
                continue
            return ValidationResult(is_valid=False, sql=sql, error_message=guard_err, attempts=attempt)

        dry_err = _dry_run(sql, context.server, context.database)
        if dry_err is None:
            return ValidationResult(is_valid=True, sql=sql, attempts=attempt)

        if attempt < _MAX_RETRIES:
            sql = _llm_correct(sql, dry_err, context, schema_block, llm_client, temperature)
        else:
            return ValidationResult(is_valid=False, sql=sql, error_message=dry_err, attempts=attempt)

    return ValidationResult(is_valid=False, sql=sql, attempts=_MAX_RETRIES)


def _sqlparse_guard(sql: str) -> str | None:
    """Reject non-SELECT statements and block forbidden keywords."""
    parsed = sqlparse.parse(sql.strip())
    if not parsed:
        return "Empty or unparseable SQL."
    first_token = parsed[0].get_type()
    if first_token != "SELECT":
        return f"Only SELECT statements are allowed; got statement type: {first_token!r}."
    lowered = sql.lower()
    for kw in _FORBIDDEN:
        if kw in lowered:
            return f"Forbidden keyword detected: {kw!r}."
    return None


def _dry_run(sql: str, server: str, database: str) -> str | None:
    """
    SET NOEXEC ON compiles the SQL on the server — resolves table/column names
    and types — without executing. Returns None if valid, error string if not.
    """
    import pyodbc

    if server not in SERVERS:
        return f"Unknown server alias '{server}'."

    cfg = SERVERS[server]
    conn_str = build_odbc_conn_str(cfg, database)
    try:
        with pyodbc.connect(conn_str, autocommit=True, timeout=10) as conn:
            cursor = conn.cursor()
            cursor.execute("SET NOEXEC ON")
            try:
                cursor.execute(sql)
            finally:
                cursor.execute("SET NOEXEC OFF")
        return None
    except Exception as exc:
        return str(exc)


def _llm_correct(
    sql: str,
    error: str,
    context: SchemaContext,
    schema_block: str,
    llm_client: genai.Client,
    temperature: float,
) -> str:
    prompt = SQL_CORRECT_USER.format(
        question=context.question,
        sql=sql,
        error=error,
        schema_block=schema_block,
    )
    resp = llm_client.models.generate_content(
        model=_CORRECT_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SQL_CORRECT_SYSTEM,
            temperature=temperature,
        ),
    )
    return extract_sql_from_response(resp.text.strip())
