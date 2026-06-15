import os
from dataclasses import dataclass, field

from vanna.integrations.google import GeminiLlmService
from vanna.integrations.mssql import MSSQLRunner


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------

llm = GeminiLlmService(
    model="gemini-2.5-pro",
    api_key=os.getenv("GOOGLE_API_KEY"),
)


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


def get_runner(server: str, database: str) -> MSSQLRunner:
    """Return an MSSQLRunner for the given server alias and database name.

    Args:
        server:   Key from SERVERS (e.g. "server1").
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

    conn_str = build_odbc_conn_str(cfg, database)
    return MSSQLRunner(odbc_conn_str=conn_str)


def list_targets() -> list[tuple[str, str]]:
    """Return all (server, database) pairs across every configured server."""
    return [
        (server, db)
        for server, cfg in SERVERS.items()
        for db in cfg.databases
    ]