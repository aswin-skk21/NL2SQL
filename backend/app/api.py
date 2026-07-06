from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException 
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"

_state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    from google import genai
    from app.pipeline.embedder import Embedder
    from scripts.schema_cache import load_cache, load_embeddings

    api_key = os.environ["GOOGLE_API_KEY"]
    _state["llm_client"] = genai.Client(api_key=api_key)
    _state["embedder"] = Embedder(api_key=api_key)
    _state["cache"] = load_cache()
    _state["table_embeddings"] = load_embeddings()
    yield
    _state.clear()


app = FastAPI(title="NL2SQL API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class QueryRequest(BaseModel):
    question: str


class QueryResponse(BaseModel):
    question: str
    answer: str
    sql: str
    rows: Optional[list[dict]] = None
    columns: Optional[list[str]] = None
    row_count: int = 0
    validation_attempts: int
    error: Optional[str] = None




@app.post("/api/query", response_model=QueryResponse)
async def query(req: QueryRequest):
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    from app.pipeline.router import route
    from app.pipeline.sql_generator import generate_sql
    from app.pipeline.validator import validate_and_correct
    from app.pipeline.executor import execute_sql
    from app.pipeline.answerer import generate_answer

    try:
        context = route(
            req.question,
            _state["cache"],
            _state["table_embeddings"],
            _state["embedder"],
            _state["llm_client"],
        )

        generated = generate_sql(context, _state["llm_client"])
        validation = validate_and_correct(generated, context, _state["llm_client"])

        if not validation.is_valid:
            return QueryResponse(
                question=req.question,
                answer=f"Could not produce valid SQL after {validation.attempts} attempt(s).",
                sql=validation.sql,
                validation_attempts=validation.attempts,
                error=validation.error_message,
            )

        exec_result = execute_sql(validation, context.server, context.database)
        answer = generate_answer(req.question, exec_result, _state["llm_client"])

        rows = None
        columns = None
        if exec_result.df is not None and not exec_result.df.empty:
            df = exec_result.df.head(100)
            columns = df.columns.tolist()
            rows = df.to_dict(orient="records")

        return QueryResponse(
            question=req.question,
            answer=answer,
            sql=validation.sql,
            rows=rows,
            columns=columns,
            row_count=exec_result.row_count,
            validation_attempts=validation.attempts,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
