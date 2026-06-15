"""Discover databases on each configured SQL Server and update config.py.

Usage:
    python discover_databases.py          # interactive: pick databases per server
    python discover_databases.py --all    # accept all databases on every server
    python discover_databases.py --dry-run  # show what would be written, don't save
"""

from __future__ import annotations

import pathlib
import re
import sys

# Make backend/ importable regardless of which directory this is run from
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import env_loader
env_loader.load()

from app.config import SERVERS

_CONFIG_PATH = pathlib.Path(__file__).parent.parent / "app" / "config.py"

_LIST_DBS_SQL = """
SELECT name
FROM sys.databases
WHERE database_id > 4
  AND state_desc = 'ONLINE'
  AND name NOT IN ('ReportServer', 'ReportServerTempDB')
ORDER BY name;
"""


def _connect_and_list(server_alias: str) -> list[str]:
    import pyodbc
    from app.config import build_odbc_conn_str

    cfg = SERVERS[server_alias]
    conn_str = build_odbc_conn_str(cfg, "master")
    try:
        with pyodbc.connect(conn_str, autocommit=True, timeout=10) as conn:
            cursor = conn.cursor()
            cursor.execute(_LIST_DBS_SQL)
            return [row.name for row in cursor.fetchall()]
    except Exception as exc:
        print(f"  [!] Could not connect to {server_alias}: {exc}")
        return []


def _pick_interactively(server_alias: str, databases: list[str]) -> list[str]:
    if not databases:
        return []
    print(f"\n  Databases found on '{server_alias}':")
    for i, db in enumerate(databases, 1):
        print(f"    [{i}] {db}")
    raw = input(
        "  Enter numbers to EXCLUDE (comma-separated), or press Enter to keep all: "
    ).strip()
    if not raw:
        return databases
    excluded = {int(x.strip()) for x in raw.split(",") if x.strip().isdigit()}
    return [db for i, db in enumerate(databases, 1) if i not in excluded]


def _update_config(alias: str, databases: list[str], content: str) -> str:
    """Replace databases=[...] inside the ServerConfig block for the given alias."""
    db_repr = "[" + ", ".join(f'"{db}"' for db in databases) + "]"

    alias_pat = re.compile(rf'"{re.escape(alias)}"\s*:\s*ServerConfig\(')
    m = alias_pat.search(content)
    if not m:
        print(f"  [!] Alias '{alias}' not found in config.py — skipping.")
        return content

    # Walk forward from the opening paren of ServerConfig(...) to find its extent
    paren_start = content.index("(", m.end() - 1)
    depth = 0
    block_end = paren_start
    for i, ch in enumerate(content[paren_start:]):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                block_end = paren_start + i + 1
                break

    block = content[m.start() : block_end]
    new_block = re.sub(r"databases=\[[^\]]*\]", f"databases={db_repr}", block)
    return content[: m.start()] + new_block + content[block_end:]


def main() -> None:
    accept_all = "--all" in sys.argv
    dry_run = "--dry-run" in sys.argv

    print("=" * 60)
    print("NL2SQL — Database Discovery")
    print("=" * 60)

    content = _CONFIG_PATH.read_text(encoding="utf-8")
    any_found = False

    for alias in SERVERS:
        print(f"\nConnecting to '{alias}' …")
        databases = _connect_and_list(alias)

        if not databases:
            print("  (no databases found or connection failed)")
            continue

        any_found = True

        if accept_all:
            chosen = databases
            print(f"  Accepting all {len(chosen)} databases.")
        else:
            chosen = _pick_interactively(alias, databases)

        if chosen:
            print(f"  → Will set databases={chosen}")
            content = _update_config(alias, chosen, content)
        else:
            print("  → No databases selected; leaving as-is.")

    if not any_found:
        print(
            "\nNo servers were reachable. Run this script on the Windows RDP "
            "machine where Windows Authentication is active."
        )
        return

    if dry_run:
        print("\n--- DRY RUN: config.py would become ---\n")
        print(content)
        return

    _CONFIG_PATH.write_text(content, encoding="utf-8")
    print(f"\nconfig.py updated. Run 'python schema_cache.py' next to rebuild the cache.")


if __name__ == "__main__":
    main()
