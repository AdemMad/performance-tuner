# Performance Tuner

Performance Tuner is a Python package for profiling analytical datasets and producing layout recommendations for faster queries. It can inspect local Parquet files or sampled warehouse query results, then suggest partitioning, clustering, bucketing, indexing, compaction, and platform-specific tuning strategies.

Package name:

```bash
performance-tuner
```

Import name:

```python
from performance_tuner import SmartAdvisor
```

Authors: Codex and Adem Madoun.

## Features

- Profile local Parquet datasets.
- Sample data from Snowflake, Databricks, Azure SQL, SQL Server, and PostgreSQL.
- Score columns for partitioning, clustering, bucketing, and indexing.
- Generate platform-aware recommendations.
- Simulate clustering metadata to show min/max pruning behavior.
- Analyze common filter combinations and recommend better physical layouts.

## Installation

Install directly from GitHub:

```bash
pip install git+https://github.com/AdemMad/performance-tuner.git
```

For local development from a cloned checkout:

```bash
pip install -e .
```

The base install includes `polars`. Install optional extras for specific sources:

```bash
pip install "performance-tuner[config]"
pip install "performance-tuner[parquet]"
pip install "performance-tuner[snowflake]"
pip install "performance-tuner[databricks]"
pip install "performance-tuner[mssql]"
pip install "performance-tuner[postgres]"
pip install "performance-tuner[all]"
```

If installing from a local checkout with extras:

```bash
pip install -e ".[all]"
```

## Project Structure

```text
.
+-- advisor/              # Core profiling, recommendation, simulation, and analysis logic
+-- connectors/           # Warehouse connectors
+-- performance_tuner/    # Public package import wrapper
+-- config.yaml           # Default settings and optional connection details
+-- main.py               # Entry point and usage examples
+-- models.py             # Dataclass report and recommendation models
+-- pyproject.toml        # Package metadata and dependency definitions
+-- utils.py              # Shared helper functions
```

## Configuration

Edit `config.yaml` to set default profiling options and optional warehouse connection details.

Sensitive values such as passwords and tokens should preferably be passed at runtime or provided through environment variables rather than committed into `config.yaml`.

Useful defaults:

```yaml
defaults:
  sample_rows: 250_000
  target_file_size_mb: 200
  platform: generic
```

Supported platform values:

```text
generic, databricks, snowflake, fabric, sqlserver, azuresql, postgres
```

## Use With a Parquet File

```python
from performance_tuner import SmartAdvisor

advisor = SmartAdvisor.from_parquet(
    path=r"C:\path\to\your\file.parquet",
    sample_rows=250_000,
    target_file_size_mb=200,
    platform="databricks",
    platform_options={
        "use_liquid_clustering": True,
        "use_zorder": False,
        "max_partition_columns": 2,
    },
)

advisor.print_dataset_summary()
```

## Use With a Warehouse Query

```python
from performance_tuner import SmartAdvisor

advisor = SmartAdvisor.from_warehouse(
    storage="snowflake",
    auth={
        "account": "xy12345.eu-west-1",
        "user": "YOUR_USER",
        "password": "YOUR_PASSWORD",
        "database": "FOOTBALL",
        "schema": "PUBLIC",
        "warehouse": "COMPUTE_WH",
    },
    query="SELECT * FROM tracking WHERE match_id IN (1, 2)",
    platform="snowflake",
)

advisor.print_dataset_summary()
```

Supported `storage` values:

```text
snowflake, databricks, azure_sql, sqlserver, postgres
```

## Simulate Clustering

Use simulated clustering metadata to understand how sorting by a candidate key can improve data skipping or pruning.

```python
advisor.print_simulated_clustering_metadata(
    clustering_columns=["match_id"],
    table_name="tracking",
    rows_per_file=500,
)
```

## Analyze Filter Patterns

Use filter analysis when you know common query predicates.

```python
advisor.print_filter_analysis(
    filter_columns=["match_id", "period"],
    simulate_metadata=True,
)
```

The advisor estimates selectivity, describes the current layout fit, and recommends partition, cluster, bucket, index, or derived-column strategies where relevant.

## Development

Run the examples in `main.py` from a checkout:

```bash
python main.py
```

Build a distributable package:

```bash
python -m build
```

## Notes

- Warehouse methods sample query results into a local in-memory profile before generating recommendations.
- Recommendation quality depends on representative samples. Increase `sample_rows` for better cardinality estimates on large or skewed datasets.
- This tool provides advisory output; validate changes against real query plans and workload metrics before applying them to production tables.
