import os
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Connection limits
#
# CONNECT_TIMEOUT bounds how long we wait to open a socket to SQL Server.
# QUERY_TIMEOUT bounds how long a single statement may run — without it an
# LLM-generated query can pin a production server indefinitely.
# ---------------------------------------------------------------------------

CONNECT_TIMEOUT = int(os.getenv("NL2SQL_CONNECT_TIMEOUT", "10"))
QUERY_TIMEOUT = int(os.getenv("NL2SQL_QUERY_TIMEOUT", "60"))
MAX_ROWS = int(os.getenv("NL2SQL_MAX_ROWS", "5000"))


# ---------------------------------------------------------------------------
# SQL Server configuration
# ---------------------------------------------------------------------------

@dataclass
class ServerConfig:
    host: str
    databases: list[str]
    windows_auth: bool = True
    # port=None omits it from the connection string; named instances (host\instance)
    # must omit the port — SQL Server Browser resolves the port dynamically.
    port: int | None = None
    username: str = ""
    password: str = ""
    driver: str = "ODBC Driver 18 for SQL Server"
    extra_params: dict[str, str] = field(default_factory=dict)


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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_odbc_conn_str(cfg: ServerConfig, database: str) -> str:
    """Return a pyodbc connection string for the given server config and database."""
    server = f"{cfg.host},{cfg.port}" if cfg.port is not None else cfg.host
    parts: dict[str, str] = {
        "DRIVER": f"{{{cfg.driver}}}",
        "SERVER": server,
        "DATABASE": database,
        **cfg.extra_params,
    }
    if cfg.windows_auth:
        parts["Trusted_Connection"] = "yes"
    else:
        parts["UID"] = cfg.username
        parts["PWD"] = cfg.password
    return ";".join(f"{k}={v}" for k, v in parts.items())


def resolve_conn_str(server: str, database: str) -> str:
    """Return a validated ODBC connection string for a server alias + database.

    Validating against SERVERS keeps an LLM-chosen (server, database) pair from
    reaching a target that was never configured.

    Args:
        server:   Key from SERVERS (e.g. "sqlProd1").
        database: Database name that must exist in ServerConfig.databases.

    Raises:
        KeyError:  Unknown server alias.
        ValueError: Database not listed for that server.
    """
    if server not in SERVERS:
        raise KeyError(f"Unknown server '{server}'. Available: {list(SERVERS)}")

    cfg = SERVERS[server]
    if database not in cfg.databases:
        raise ValueError(
            f"Database '{database}' not found on '{server}'. "
            f"Available: {cfg.databases}"
        )

    return build_odbc_conn_str(cfg, database)


def list_targets() -> list[tuple[str, str]]:
    """Return all (server, database) pairs across every configured server."""
    return [
        (server, db)
        for server, cfg in SERVERS.items()
        for db in cfg.databases
    ]