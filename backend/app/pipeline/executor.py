from __future__ import annotations

import asyncio

from vanna.capabilities.sql_runner.models import RunSqlToolArgs

from ..config import get_runner
from ..models import ExecutionResult, ValidationResult


def execute_sql(result: ValidationResult, server: str, database: str) -> ExecutionResult:
    if not result.is_valid:
        raise ValueError(
            f"Cannot execute invalid SQL after {result.attempts} attempt(s): "
            f"{result.error_message}"
        )
    runner = get_runner(server, database)
    args = RunSqlToolArgs(sql=result.sql)
    df = asyncio.run(runner.run_sql(args, context=None))  # type: ignore[arg-type]
    return ExecutionResult(df=df, row_count=len(df), sql_executed=result.sql)
