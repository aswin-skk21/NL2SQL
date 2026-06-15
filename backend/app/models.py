from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd


@dataclass
class ColumnInfo:
    name: str
    data_type: str
    is_nullable: bool
    max_length: Optional[int] = None
    description: str = ""


@dataclass
class TableInfo:
    server: str
    database: str
    schema: str
    table: str
    columns: list[ColumnInfo] = field(default_factory=list)
    row_count_estimate: Optional[int] = None
    embedding_token: str = ""


@dataclass
class SchemaCache:
    tables: list[TableInfo] = field(default_factory=list)
    built_at: str = ""


@dataclass
class SchemaContext:
    question: str
    relevant_tables: list[TableInfo]
    server: str
    database: str


@dataclass
class GeneratedSQL:
    sql: str
    explanation: str = ""


@dataclass
class ValidationResult:
    is_valid: bool
    sql: str
    error_message: str = ""
    attempts: int = 1


@dataclass
class ExecutionResult:
    df: pd.DataFrame
    row_count: int
    sql_executed: str


@dataclass
class PipelineResult:
    question: str
    answer: str
    sql: str
    df: Optional[pd.DataFrame]
    validation_attempts: int
    error: Optional[str] = None
