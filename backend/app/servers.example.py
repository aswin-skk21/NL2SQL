"""Template for servers.py — copy this file to servers.py and run
`python scripts/discover_databases.py` to populate the `databases` lists, or
fill them in by hand. servers.py is gitignored: once populated it names a
full database inventory, which shouldn't live in source control.
"""

from __future__ import annotations

from .config import ServerConfig

SERVERS: dict[str, ServerConfig] = {
    "dataTM1": ServerConfig(
        host="dataTM1",
        databases=[],
    ),
    "sqlProd1": ServerConfig(
        host="sqlProd1",
        databases=[],
    ),
    "sqlDev1": ServerConfig(
        host="sqlDev1",
        databases=[],
    ),
    "sqlProd1_org": ServerConfig(
        host=r"sqlProd1\org",
        databases=[],
    ),
    "sqlProd1_sf": ServerConfig(
        host=r"sqlProd1\sf",
        databases=[],
    ),
    "sqlProd1_x": ServerConfig(
        host=r"sqlProd1\x",
        databases=[],
    ),
    "sqlSTG1": ServerConfig(
        host="sqlSTG1",
        databases=[],
    ),
}
