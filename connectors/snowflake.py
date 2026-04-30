from __future__ import annotations

from typing import Any, Dict

import polars as pl

from .base import BaseConnector


class SnowflakeConnector(BaseConnector):
    """
    Fetch data from Snowflake via snowflake-connector-python.

    Required auth keys
    ------------------
    account   : str  e.g. "xy12345.eu-west-1"
    user      : str
    password  : str
    database  : str
    schema    : str
    warehouse : str

    Optional auth keys
    ------------------
    role      : str   Snowflake role to assume
    login_timeout : int  seconds (default 60)

    Install
    -------
    pip install snowflake-connector-python[pandas]
    """

    def fetch(self, query: str) -> pl.DataFrame:
        try:
            import snowflake.connector  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "snowflake-connector-python is required for Snowflake connections. "
                "Install it with: pip install snowflake-connector-python[pandas]"
            ) from exc

        conn_kwargs: Dict[str, Any] = {
            "account":   self.auth["account"],
            "user":      self.auth["user"],
            "password":  self.auth["password"],
            "database":  self.auth["database"],
            "schema":    self.auth["schema"],
            "warehouse": self.auth["warehouse"],
        }
        if "role" in self.auth:
            conn_kwargs["role"] = self.auth["role"]
        if "login_timeout" in self.auth:
            conn_kwargs["login_timeout"] = self.auth["login_timeout"]

        conn   = snowflake.connector.connect(**conn_kwargs)
        cursor = conn.cursor()
        try:
            cursor.execute(query)
            # fetch_pandas_all() returns a pandas DataFrame efficiently
            pd_df = cursor.fetch_pandas_all()
        finally:
            cursor.close()
            conn.close()

        return pl.from_pandas(pd_df)
