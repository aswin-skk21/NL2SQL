from __future__ import annotations

import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"

logger = logging.getLogger("nl2sql")

_state: dict = {}


def _require_env(name: str, hint: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is not set. {hint}")
    return value


@asynccontextmanager
async def lifespan(app: FastAPI):
    from google import genai
    from app.pipeline.embedder import Embedder
    from scripts.schema_cache import CACHE_PATH, load_cache, load_embeddings

    api_key = _require_env(
        "GOOGLE_API_KEY",
        "Add it to .env at the repo root or set it in the service environment.",
    )
    # Fail closed: this endpoint runs LLM-generated SQL against production.
    _state["api_token"] = _require_env(
        "NL2SQL_API_TOKEN",
        'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(32))"',
    )

    if not CACHE_PATH.exists():
        raise RuntimeError(
            f"Schema cache not found at {CACHE_PATH}. Run "
            "'python scripts/discover_databases.py' then "
            "'python scripts/schema_cache.py' on a machine with SQL Server access."
        )

    _state["llm_client"] = genai.Client(api_key=api_key)
    _state["embedder"] = Embedder(api_key=api_key)
    _state["cache"] = load_cache()
    _state["table_embeddings"] = load_embeddings()

    table_count = len(_state["cache"].tables)
    if table_count == 0:
        logger.warning(
            "Schema cache is empty — every query will fail. Populate the "
            "'databases' lists in app/config.py and re-run scripts/schema_cache.py."
        )
    logger.info("NL2SQL ready — %d tables cached", table_count)

    yield
    _state.clear()


app = FastAPI(title="NL2SQL API", version="1.0.0", lifespan=lifespan)

# The frontend is served same-origin from this app (and the Vite dev server
# proxies /api), so no cross-origin access is needed by default. Set
# NL2SQL_CORS_ORIGINS to a comma-separated list only if you host the UI apart.
_cors_origins = [
    o.strip() for o in os.getenv("NL2SQL_CORS_ORIGINS", "").split(",") if o.strip()
]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )


def require_token(authorization: str = Header(default="")) -> None:
    """Shared-token auth. Send 'Authorization: Bearer <NL2SQL_API_TOKEN>'."""
    expected = _state.get("api_token", "")
    supplied = authorization.removeprefix("Bearer ").strip()
    # Constant-time compare so a wrong token can't be narrowed down by timing.
    if not expected or not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing API token.")


class QueryRequest(BaseModel):
    question: str


class QueryResponse(BaseModel):
    question: str
    answer: str
    sql: str
    rows: Optional[list[dict]] = None
    columns: Optional[list[str]] = None
    row_count: int = 0
    truncated: bool = False
    validation_attempts: int
    error: Optional[str] = None


@app.get("/api/health")
def health() -> dict:
    cache = _state.get("cache")
    return {
        "status": "ok" if cache is not None else "starting",
        "tables_cached": len(cache.tables) if cache is not None else 0,
        "cache_built_at": cache.built_at if cache is not None else None,
    }


# Defined with `def`, not `async def`: the pipeline does blocking network and
# ODBC I/O, so FastAPI runs it in a worker thread. Declaring it async would
# both stall the event loop and break the executor's database call.
@app.post(
    "/api/query", response_model=QueryResponse, dependencies=[Depends(require_token)]
)
def query(req: QueryRequest) -> QueryResponse:
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

        if not context.relevant_tables:
            return QueryResponse(
                question=req.question,
                answer="No tables in the schema cache matched that question.",
                sql="",
                validation_attempts=0,
                error="Router selected no tables.",
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
            # NaN/NaT are not valid JSON — convert them to null.
            rows = df.astype(object).where(df.notna(), None).to_dict(orient="records")

        return QueryResponse(
            question=req.question,
            answer=answer,
            sql=validation.sql,
            rows=rows,
            columns=columns,
            row_count=exec_result.row_count,
            truncated=exec_result.truncated,
            validation_attempts=validation.attempts,
        )
    except HTTPException:
        raise
    except Exception as exc:
        # Log detail server-side; don't leak connection strings or schema
        # internals to the browser unless explicitly debugging.
        logger.exception("Query failed: %s", req.question)
        detail = (
            f"{type(exc).__name__}: {exc}"
            if os.getenv("NL2SQL_DEBUG_ERRORS") == "1"
            else "Query failed. Check the server log for details."
        )
        raise HTTPException(status_code=500, detail=detail)


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
else:
    logger.warning(
        "Frontend build not found at %s — serving API only. Run 'npm ci && "
        "npm run build' in frontend/.",
        FRONTEND_DIR,
    )
