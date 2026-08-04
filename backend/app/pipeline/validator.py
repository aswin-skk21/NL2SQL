from __future__ import annotations

import sqlparse
from google import genai
from google.genai import types
from sqlparse import tokens as T

from ..config import CONNECT_TIMEOUT, resolve_conn_str
from ..models import GeneratedSQL, SchemaContext, ValidationResult
from ..prompts import SQL_CORRECT_SYSTEM, SQL_CORRECT_USER
from .sql_generator import _format_schema_block, extract_sql_from_response

_MAX_RETRIES = 3
_CORRECT_MODEL = "gemini-flash-lite-latest"

# Matched against parsed *keyword tokens* only — never as substrings, or ordinary
# columns like UpdatedDate / IsDeleted / ExecutionTime would be rejected.
_FORBIDDEN_KEYWORDS = {
    "drop", "insert", "update", "delete", "truncate", "exec", "execute",
    "merge", "alter", "create", "grant", "revoke", "shutdown", "backup",
    "restore", "into",
}

# Functions that can reach data outside the selected database.
_FORBIDDEN_NAMES = {"openrowset", "opendatasource", "openquery", "openxml"}


def validate_and_correct(
    generated: GeneratedSQL,
    context: SchemaContext,
    llm_client: genai.Client,
    temperature: float = 0.1,
) -> ValidationResult:
    sql = generated.sql
    schema_block = _format_schema_block(context.relevant_tables)

    for attempt in range(1, _MAX_RETRIES + 1):
        guard_err = _sqlparse_guard(sql) or _cross_database_guard(sql, context.database)
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
    """Reject anything that is not a single read-only SELECT statement.

    Checks keyword *tokens* rather than raw substrings: a substring scan rejects
    legitimate queries that merely mention a column named UpdatedDate,
    IsDeleted or ExecutionTime.
    """
    statements = [s for s in sqlparse.parse(sql.strip()) if str(s).strip(" ;\n\t")]
    if not statements:
        return "Empty or unparseable SQL."
    if len(statements) > 1:
        # Blocks stacked queries such as "SELECT 1; DROP TABLE x".
        return f"Only a single statement is allowed; got {len(statements)}."

    statement = statements[0]
    stmt_type = statement.get_type()
    if stmt_type != "SELECT":
        return f"Only SELECT statements are allowed; got statement type: {stmt_type!r}."

    for token in statement.flatten():
        if token.ttype in (T.Keyword, T.Keyword.DML, T.Keyword.DDL, T.Keyword.CTE):
            if token.normalized.lower() in _FORBIDDEN_KEYWORDS:
                return f"Forbidden keyword detected: {token.normalized.upper()!r}."
        value = token.value.strip('[]"').lower()
        if value in _FORBIDDEN_NAMES:
            return f"Forbidden function detected: {token.value!r}."
        if value.startswith("xp_") and (token.ttype in T.Name or token.ttype in T.Keyword):
            return f"Forbidden extended stored procedure: {token.value!r}."
    return None


def _cross_database_guard(sql: str, database: str) -> str | None:
    """Reject table references that escape the routed database.

    The router picks one (server, database) pair and the connection is opened
    against `database`, but T-SQL lets a query name a different database (or
    even a different linked server) right in the FROM clause via dotted
    identifiers — `OtherDb.dbo.Table` or `srv.OtherDb.dbo.Table` — which
    `SET NOEXEC ON` happily compiles if the connection's login can read it.
    Since the login is a shared Windows service account with read access
    across many databases, that's a silent way out of the schema the router
    selected. Only two-part (schema.table) and one-part (table) references are
    implicitly database-scoped and always allowed.
    """
    statement = sqlparse.parse(sql.strip())[0]
    tokens = [t for t in statement.flatten() if not t.is_whitespace]
    n = len(tokens)
    i = 0
    while i < n:
        tok = tokens[i]
        if tok.ttype in T.Name:
            first = tok
            j = i + 1
            dots = 0
            while j < n and tokens[j].ttype is T.Punctuation and tokens[j].value == ".":
                dots += 1
                j += 1
                if j < n and tokens[j].ttype in T.Name:
                    j += 1
            if dots >= 2:
                named = first.value.strip('[]"').lower()
                if dots >= 3 or named != database.lower():
                    return (
                        f"Cross-database reference to {first.value!r} is not "
                        f"allowed; the query must stay within '{database}'."
                    )
            i = j
        else:
            i += 1
    return None


def _dry_run(sql: str, server: str, database: str) -> str | None:
    """
    SET NOEXEC ON compiles the SQL on the server — resolves table/column names
    and types — without executing. Returns None if valid, error string if not.
    """
    import pyodbc

    try:
        conn_str = resolve_conn_str(server, database)
    except (KeyError, ValueError) as exc:
        return str(exc)

    try:
        with pyodbc.connect(conn_str, autocommit=True, timeout=CONNECT_TIMEOUT) as conn:
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
            thinking_config=types.ThinkingConfig(thinking_budget=1),
        ),
    )
    return extract_sql_from_response(resp.text.strip())
