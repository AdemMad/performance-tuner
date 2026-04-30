from __future__ import annotations

from typing import Any, Dict

import polars as pl

from .base import BaseConnector


class SQLServerConnector(BaseConnector):
    """
    Fetch data from SQL Server (on-prem or VM) via pyodbc.

    Required auth keys
    ------------------
    server   : str   e.g. "MYSERVER\\SQLEXPRESS" or "192.168.1.10"
    database : str

    Optional auth keys
    ------------------
    username : str   SQL auth username (omit for Windows auth)
    password : str   SQL auth password (omit for Windows auth)
    driver   : str   ODBC driver name
                     default "ODBC Driver 18 for SQL Server"
    port     : int   default 1433
    encrypt  : bool  default False  (on-prem usually doesn't require TLS)
    trust_server_certificate : bool  default True

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
                "pyodbc and pandas are required for SQL Server connections. "
                "Install them with: pip install pyodbc pandas"
            ) from exc

        driver  = self.auth.get("driver", self._DEFAULT_DRIVER)
        port    = self.auth.get("port", 1433)
        encrypt = "yes" if self.auth.get("encrypt", False) else "no"
        trust   = "yes" if self.auth.get("trust_server_certificate", True) else "no"

        server_str = f"{self.auth['server']},{port}"

        if "username" in self.auth and "password" in self.auth:
            # SQL Server authentication
            conn_str = (
                f"DRIVER={{{driver}}};"
                f"SERVER={server_str};"
                f"DATABASE={self.auth['database']};"
                f"UID={self.auth['username']};"
                f"PWD={self.auth['password']};"
                f"Encrypt={encrypt};"
                f"TrustServerCertificate={trust};"
            )
        else:
            # Windows / integrated authentication
            conn_str = (
                f"DRIVER={{{driver}}};"
                f"SERVER={server_str};"
                f"DATABASE={self.auth['database']};"
                f"Trusted_Connection=yes;"
                f"Encrypt={encrypt};"
                f"TrustServerCertificate={trust};"
            )

        conn = pyodbc.connect(conn_str)
        try:
            pd_df = pd.read_sql(query, conn)
        finally:
            conn.close()

        return pl.from_pandas(pd_df)
