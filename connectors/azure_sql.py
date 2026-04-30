from __future__ import annotations

from typing import Any, Dict

import polars as pl

from .base import BaseConnector


class AzureSQLConnector(BaseConnector):
    """
    Fetch data from Azure SQL Database via pyodbc.

    Required auth keys
    ------------------
    server   : str   e.g. "myserver.database.windows.net"
    database : str
    username : str
    password : str

    Optional auth keys
    ------------------
    driver  : str   ODBC driver name
                    default "ODBC Driver 18 for SQL Server"
    port    : int   default 1433
    encrypt : bool  default True  (Azure SQL requires encryption)
    trust_server_certificate : bool  default False

    Install
    -------
    pip install pyodbc pandas
    Plus the Microsoft ODBC driver for your OS.
    """

    _DEFAULT_DRIVER = "ODBC Driver 18 for SQL Server"

    def fetch(self, query: str) -> pl.DataFrame:
        try:
            import pyodbc  # type: ignore[import]
            import pandas as pd
        except ImportError as exc:
            raise ImportError(
                "pyodbc and pandas are required for Azure SQL connections. "
                "Install them with: pip install pyodbc pandas"
            ) from exc

        driver  = self.auth.get("driver", self._DEFAULT_DRIVER)
        port    = self.auth.get("port", 1433)
        encrypt = "yes" if self.auth.get("encrypt", True) else "no"
        trust   = "yes" if self.auth.get("trust_server_certificate", False) else "no"

        conn_str = (
            f"DRIVER={{{driver}}};"
            f"SERVER={self.auth['server']},{port};"
            f"DATABASE={self.auth['database']};"
            f"UID={self.auth['username']};"
            f"PWD={self.auth['password']};"
            f"Encrypt={encrypt};"
            f"TrustServerCertificate={trust};"
        )

        conn = pyodbc.connect(conn_str)
        try:
            pd_df = pd.read_sql(query, conn)
        finally:
            conn.close()

        return pl.from_pandas(pd_df)
