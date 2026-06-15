from __future__ import annotations

import re

from google import genai
from google.genai import types

from ..models import GeneratedSQL, SchemaContext, TableInfo
from ..prompts import SQL_GEN_SYSTEM, SQL_GEN_USER

_GEN_MODEL = "gemini-2.5-pro"


def generate_sql(
    context: SchemaContext,
    llm_client: genai.Client,
    temperature: float = 0.1,
) -> GeneratedSQL:
    schema_block = _format_schema_block(context.relevant_tables)
    prompt = SQL_GEN_USER.format(
        question=context.question,
        server=context.server,
        database=context.database,
        schema_block=schema_block,
    )
    resp = llm_client.models.generate_content(
        model=_GEN_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SQL_GEN_SYSTEM,
            temperature=temperature,
        ),
    )
    full_text = resp.text.strip()
    sql = extract_sql_from_response(full_text)
    explanation = _extract_explanation(full_text)
    return GeneratedSQL(sql=sql, explanation=explanation)


def _format_schema_block(tables: list[TableInfo]) -> str:
    blocks = []
    for t in tables:
        header = f"-- [{t.schema}].[{t.table}]"
        if t.row_count_estimate is not None:
            header += f": ~{t.row_count_estimate:,} rows (est.)"
        col_lines = []
        for c in t.columns:
            nullable = "NULL" if c.is_nullable else "NOT NULL"
            length = f"({c.max_length})" if c.max_length else ""
            col_lines.append(f"    {c.name:<30} {c.data_type}{length} {nullable}")
        body = "\n".join(col_lines)
        blocks.append(
            f"{header}\n"
            f"CREATE TABLE [{t.schema}].[{t.table}] (\n{body}\n);"
        )
    return "\n\n".join(blocks)


def extract_sql_from_response(text: str) -> str:
    m = re.search(r"```sql\s*\n(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(r"\bSELECT\b.*?;", text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(0).strip()
    return text.strip()


def _extract_explanation(text: str) -> str:
    parts = text.split("```")
    if len(parts) >= 3:
        return parts[-1].strip()
    return ""
