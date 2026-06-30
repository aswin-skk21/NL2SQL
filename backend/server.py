"""FastAPI server entrypoint.

Run from the backend/ directory:
    python server.py
    # or
    uvicorn app.api:app --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import env_loader
env_loader.load()

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.api:app", host="0.0.0.0", port=8000, reload=False)
