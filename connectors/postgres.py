from __future__ import annotations

from typing import Any, Dict

import polars as pl

from .base import BaseConnector


class PostgresConnector(BaseConnector):
    """
    Fetch data from PostgreSQL via psycopg2.

    Required auth keys
    ------------------
    host     : str   e.g. "localhost" or "mydb.postgres.database.azure.com"
    database : str
    user     : str
    password : str

    Optional auth keys
    ------------------
    port    : int   default 5432
    sslmode : str   e.g. "require", "disable"  (default: not set)
    options : str   libpq extra options string

    Install
    -------
    pip install psycopg2-binary pandas
    (or psycopg2 for a compiled build)
    """

    def fetch(self, query: str) -> pl.DataFrame:
        try:
            import psycopg2  # type: ignore[import]
            import pandas as pd
        except ImportError as exc:
            raise ImportError(
                "psycopg2 and pandas are required for PostgreSQL connections. "
                "Install them with: pip install psycopg2-binary pandas"
            ) from exc

        conn_kwargs: Dict[str, Any] = {
            "host":     self.auth["host"],
            "dbname":   self.auth["database"],
            "user":     self.auth["user"],
            "password": self.auth["password"],
            "port":     self.auth.get("port", 5432),
        }
        if "sslmode" in self.auth:
            conn_kwargs["sslmode"] = self.auth["sslmode"]
        if "options" in self.auth:
            conn_kwargs["options"] = self.auth["options"]

        conn = psycopg2.connect(**conn_kwargs)
        try:
            pd_df = pd.read_sql(query, conn)
        finally:
            conn.close()

        return pl.from_pandas(pd_df)
