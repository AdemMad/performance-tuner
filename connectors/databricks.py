from __future__ import annotations

from typing import Any, Dict

import polars as pl

from .base import BaseConnector


class DatabricksConnector(BaseConnector):
    """
    Fetch data from Databricks via databricks-sql-connector.

    Required auth keys
    ------------------
    server_hostname : str   e.g. "adb-1234567890.1.azuredatabricks.net"
    http_path       : str   e.g. "/sql/1.0/warehouses/abc123"
    access_token    : str   Personal access token

    Optional auth keys
    ------------------
    catalog     : str   Unity Catalog name (default: use session default)
    schema_name : str   Schema / database name
    staging_allowed_local_path : str  For staging uploads (rare)

    Install
    -------
    pip install databricks-sql-connector
    """

    def fetch(self, query: str) -> pl.DataFrame:
        try:
            from databricks import sql as dbsql  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "databricks-sql-connector is required for Databricks connections. "
                "Install it with: pip install databricks-sql-connector"
            ) from exc

        conn_kwargs: Dict[str, Any] = {
            "server_hostname": self.auth["server_hostname"],
            "http_path":       self.auth["http_path"],
            "access_token":    self.auth["access_token"],
        }
        if "catalog" in self.auth:
            conn_kwargs["catalog"] = self.auth["catalog"]
        if "schema_name" in self.auth:
            conn_kwargs["schema"] = self.auth["schema_name"]

        conn   = dbsql.connect(**conn_kwargs)
        cursor = conn.cursor()
        try:
            cursor.execute(query)
            # fetchall_arrow() returns a PyArrow Table — zero-copy to Polars
            arrow_table = cursor.fetchall_arrow()
            return pl.from_arrow(arrow_table)
        finally:
            cursor.close()
            conn.close()
