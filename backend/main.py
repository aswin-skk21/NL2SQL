"""NL2SQL pipeline entry point.

Usage:
    python main.py "what are the top 10 customers by revenue?"
"""

from __future__ import annotations

import os
import sys

import env_loader
env_loader.load()

from google import genai

from app.pipeline.answerer import generate_answer
from app.pipeline.embedder import Embedder
from app.pipeline.executor import execute_sql
from app.models import PipelineResult
from app.pipeline.router import route
from scripts.schema_cache import load_cache, load_embeddings
from app.pipeline.sql_generator import generate_sql
from app.pipeline.validator import validate_and_correct


def run_pipeline(question: str) -> PipelineResult:
    api_key = os.environ["GOOGLE_API_KEY"]
    llm_client = genai.Client(api_key=api_key)
    embedder = Embedder(api_key=api_key)

    cache = load_cache()
    table_embeddings = load_embeddings()

    print("[1/6] Routing to schema …")
    context = route(question, cache, table_embeddings, embedder, llm_client)
    print(f"      → {context.server} / {context.database} ({len(context.relevant_tables)} tables)")

    print("[2/6] Generating SQL …")
    generated = generate_sql(context, llm_client)

    print("[3/6] Validating SQL …")
    validation = validate_and_correct(generated, context, llm_client)
    print(f"      → {'valid' if validation.is_valid else 'INVALID'} after {validation.attempts} attempt(s)")

    if not validation.is_valid:
        return PipelineResult(
            question=question,
            answer=(
                f"Could not produce valid SQL after {validation.attempts} attempt(s). "
                f"Last error: {validation.error_message}"
            ),
            sql=validation.sql,
            df=None,
            validation_attempts=validation.attempts,
            error=validation.error_message,
        )

    print("[4/6] Executing SQL …")
    exec_result = execute_sql(validation, context.server, context.database)
    print(f"      → {exec_result.row_count} rows returned")

    print("[5/6] Generating answer …")
    answer = generate_answer(question, exec_result, llm_client)

    return PipelineResult(
        question=question,
        answer=answer,
        sql=validation.sql,
        df=exec_result.df,
        validation_attempts=validation.attempts,
    )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        question = input("Question: ").strip()
    else:
        question = " ".join(sys.argv[1:])

    result = run_pipeline(question)

    print("\n" + "=" * 60)
    print(f"Answer:\n{result.answer}")
    print(f"\nSQL ({result.validation_attempts} attempt(s)):\n{result.sql}")
    if result.df is not None and not result.df.empty:
        print(f"\nFirst rows:\n{result.df.head(10).to_string(index=False)}")
