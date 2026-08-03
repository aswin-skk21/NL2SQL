"""Minimal .env loader — no external dependencies required.

Call load() at the top of any entry-point script before accessing os.environ.
Values already set in the environment (e.g. by the shell or a Windows service
definition) are never overwritten.

Looks in backend/.env first, then the repo root .env, so a fresh clone works
without needing a symlink between the two.
"""

from __future__ import annotations

import os
import pathlib

_BACKEND_ENV = pathlib.Path(__file__).parent / ".env"
_ROOT_ENV = pathlib.Path(__file__).parent.parent / ".env"


def load(path: pathlib.Path | None = None) -> pathlib.Path | None:
    """Load the first .env found. Returns the file used, or None if none exist."""
    candidates = [path] if path is not None else [_BACKEND_ENV, _ROOT_ENV]

    for candidate in candidates:
        if candidate is None or not candidate.exists():
            continue
        for raw in candidate.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))
        return candidate

    return None
