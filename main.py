"""
performance_tuner — entry point
================================
Run this file directly or import SmartAdvisor into your own scripts.

Quick-start examples are shown in the __main__ block at the bottom.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Make project root importable regardless of working directory
sys.path.insert(0, str(Path(__file__).resolve().parent))

from advisor import SmartAdvisor


# =============================================================================
# Helper: load config.yaml
# =============================================================================

def load_config(path: str | Path | None = None) -> dict:
    """
    Load config.yaml from the project root (or a custom path).
    Returns an empty dict if the file is missing or PyYAML is not installed.
    """
    config_path = Path(path) if path else Path(__file__).parent / "config.yaml"
    if not config_path.exists():
        return {}
    try:
        import yaml  # type: ignore[import]
        with config_path.open(encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        print(
            "[performance_tuner] PyYAML not installed — config.yaml not loaded. "
            "Install with: pip install pyyaml"
        )
        return {}


# =============================================================================
# __main__ examples
# =============================================================================

if __name__ == "__main__":

    cfg = load_config()
    defaults = cfg.get("defaults", {})

    # -------------------------------------------------------------------------
    # EXAMPLE 1: Parquet file (original behaviour)
    # -------------------------------------------------------------------------
    # advisor = SmartAdvisor.from_parquet(
    #     path=r"C:\path\to\your\file.parquet",
    #     sample_rows=defaults.get("sample_rows", 250_000),
    #     target_file_size_mb=defaults.get("target_file_size_mb", 200),
    #     platform="databricks",
    #     platform_options=defaults.get("platform_options", {}),
    # )
    # advisor.print_dataset_summary()

    # -------------------------------------------------------------------------
    # EXAMPLE 2: Snowflake — sample two matches, simulate clustering on match_id
    #
    # The query fetches only match_id IN (1, 2) from the table.
    # This snapshot is then sorted by match_id to show how a warehouse that is
    # CLUSTERED BY (match_id) would organise data into micro-partitions:
    #   file_001 → match_id 1→1
    #   file_002 → match_id 2→2
    # A query WHERE match_id = 1 therefore prunes file_002 entirely.
    # -------------------------------------------------------------------------
    snowflake_auth = cfg.get("snowflake", {})

    advisor = SmartAdvisor.from_warehouse(
        storage="snowflake",
        auth={
            "account":   snowflake_auth.get("account", ""),
            "user":      snowflake_auth.get("user", ""),
            "password":  snowflake_auth.get("password", ""),
            "database":  snowflake_auth.get("database", "FOOTBALL"),
            "schema":    snowflake_auth.get("schema", "PUBLIC"),
            "warehouse": snowflake_auth.get("warehouse", "COMPUTE_WH"),
        },
        query="SELECT * FROM tracking WHERE match_id IN (1, 2)",
        platform="snowflake",
    )

    # Full column profile + platform recommendations
    # advisor.print_dataset_summary()

    # Simulate how clustering on match_id would partition the data
    advisor.print_simulated_clustering_metadata(
        clustering_columns=["match_id"],
        table_name="tracking",
        rows_per_file=500,         # tune to match Snowflake micro-partition size
    )

    # Analyse a specific filter combo and see pruning advice
    # advisor.print_filter_analysis(
    #     filter_columns=["match_id", "period"],
    #     simulate_metadata=True,
    # )

    # -------------------------------------------------------------------------
    # EXAMPLE 3: Databricks
    # -------------------------------------------------------------------------
    # db_auth = cfg.get("databricks", {})
    # advisor = SmartAdvisor.from_warehouse(
    #     storage="databricks",
    #     auth={
    #         "server_hostname": db_auth.get("server_hostname", ""),
    #         "http_path":       db_auth.get("http_path", ""),
    #         "access_token":    db_auth.get("access_token", ""),
    #     },
    #     query="SELECT * FROM football.tracking WHERE match_id IN (1, 2)",
    #     platform="databricks",
    #     platform_options={"use_liquid_clustering": True},
    # )
    # advisor.print_simulated_clustering_metadata(["match_id", "period"])

    # -------------------------------------------------------------------------
    # EXAMPLE 4: Azure SQL
    # -------------------------------------------------------------------------
    # az_auth = cfg.get("azure_sql", {})
    # advisor = SmartAdvisor.from_warehouse(
    #     storage="azure_sql",
    #     auth={
    #         "server":   az_auth.get("server", ""),
    #         "database": az_auth.get("database", ""),
    #         "username": az_auth.get("username", ""),
    #         "password": az_auth.get("password", ""),
    #     },
    #     query="SELECT * FROM dbo.tracking WHERE match_id IN (1, 2)",
    #     platform="azuresql",
    # )
    # advisor.print_dataset_summary()

    # -------------------------------------------------------------------------
    # EXAMPLE 5: SQL Server (on-prem)
    # -------------------------------------------------------------------------
    # ss_auth = cfg.get("sqlserver", {})
    # advisor = SmartAdvisor.from_warehouse(
    #     storage="sqlserver",
    #     auth={
    #         "server":   ss_auth.get("server", ""),
    #         "database": ss_auth.get("database", ""),
    #         "username": ss_auth.get("username", ""),
    #         "password": ss_auth.get("password", ""),
    #     },
    #     query="SELECT * FROM dbo.tracking WHERE match_id IN (1, 2)",
    #     platform="sqlserver",
    # )
    # advisor.print_dataset_summary()

    # -------------------------------------------------------------------------
    # EXAMPLE 6: PostgreSQL
    # -------------------------------------------------------------------------
    # pg_auth = cfg.get("postgres", {})
    # advisor = SmartAdvisor.from_warehouse(
    #     storage="postgres",
    #     auth={
    #         "host":     pg_auth.get("host", "localhost"),
    #         "database": pg_auth.get("database", ""),
    #         "user":     pg_auth.get("user", ""),
    #         "password": pg_auth.get("password", ""),
    #     },
    #     query="SELECT * FROM tracking WHERE match_id IN (1, 2)",
    #     platform="postgres",
    # )
    # advisor.print_dataset_summary()
