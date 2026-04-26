from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict

import polars as pl


class BaseConnector(ABC):
    """Abstract base for all warehouse connectors."""

    def __init__(self, auth: Dict[str, Any]) -> None:
        self.auth = auth

    @abstractmethod
    def fetch(self, query: str) -> pl.DataFrame:
        """Execute *query* and return results as a Polars DataFrame."""


def get_connector(storage: str, auth: Dict[str, Any]) -> BaseConnector:
    """
    Factory: return the right connector for *storage*.

    Supported values: "snowflake", "databricks", "azure_sql", "sqlserver",
                      "postgres"
    """
    storage = storage.lower().strip()

    if storage == "snowflake":
        from .snowflake import SnowflakeConnector
        return SnowflakeConnector(auth)

    if storage == "databricks":
        from .databricks import DatabricksConnector
        return DatabricksConnector(auth)

    if storage == "azure_sql":
        from .azure_sql import AzureSQLConnector
        return AzureSQLConnector(auth)

    if storage == "sqlserver":
        from .sqlserver import SQLServerConnector
        return SQLServerConnector(auth)

    if storage == "postgres":
        from .postgres import PostgresConnector
        return PostgresConnector(auth)

    raise ValueError(
        f"Unknown storage '{storage}'. "
        f"Supported: snowflake, databricks, azure_sql, sqlserver, postgres"
    )
