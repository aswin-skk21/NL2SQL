"""Minimal .env loader — no external dependencies required.

Call load() at the top of any entry-point script before accessing os.environ.
Values already set in the environment (e.g. by the shell) are never overwritten.
"""

from __future__ import annotations

import os
import pathlib

_ENV_PATH = pathlib.Path(__file__).parent / ".env"


def load(path: pathlib.Path = _ENV_PATH) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())
