from __future__ import annotations

from google import genai
from google.genai import types

from ..models import ExecutionResult
from ..prompts import ANSWER_SYSTEM, ANSWER_USER

_ANSWER_MODEL = "gemini-2.5-flash"
_MAX_DISPLAY_ROWS = 50


def generate_answer(
    question: str,
    exec_result: ExecutionResult,
    llm_client: genai.Client,
    temperature: float = 0.3,
) -> str:
    df = exec_result.df

    if df is None or df.empty:
        table_md = "(empty result set)"
    elif len(df) > _MAX_DISPLAY_ROWS:
        table_md = df.head(_MAX_DISPLAY_ROWS).to_markdown(index=False)
        table_md += f"\n\n… and {len(df) - _MAX_DISPLAY_ROWS} more rows."
    else:
        table_md = df.to_markdown(index=False)

    prompt = ANSWER_USER.format(
        question=question,
        row_count=exec_result.row_count,
        table_markdown=table_md,
    )
    resp = llm_client.models.generate_content(
        model=_ANSWER_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=ANSWER_SYSTEM,
            temperature=temperature,
        ),
    )
    return resp.text.strip()
