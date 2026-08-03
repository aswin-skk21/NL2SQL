"""FastAPI server entrypoint.

Run from the backend/ directory:
    python server.py
    # or
    uvicorn app.api:app --host 0.0.0.0 --port 8000

Environment:
    GOOGLE_API_KEY        required — Gemini API key
    NL2SQL_API_TOKEN      required — shared token clients must send
    NL2SQL_HOST           bind address (default 0.0.0.0)
    NL2SQL_PORT           port (default 8000)
    NL2SQL_QUERY_TIMEOUT  per-statement timeout in seconds (default 60)
    NL2SQL_MAX_ROWS       max rows fetched per query (default 5000)
"""

from __future__ import annotations

import logging
import os

import env_loader

env_file = env_loader.load()

import uvicorn

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    log = logging.getLogger("nl2sql")
    log.info("Loaded environment from %s", env_file or "(no .env found)")

    uvicorn.run(
        "app.api:app",
        host=os.getenv("NL2SQL_HOST", "0.0.0.0"),
        port=int(os.getenv("NL2SQL_PORT", "8000")),
        reload=False,
    )
