# Data Warehouse Optimizer

A web app that connects to your data warehouse, profiles table columns, and provides AI-powered optimization advice using Google Gemini.

## What it does

1. **Connect** — enter credentials for Snowflake, Databricks, Azure SQL, SQL Server, or PostgreSQL.
2. **Insights** — run pre-built queries (most queried tables, clustering info, table sizes, expensive queries, column stats) — SQL auto-generated for your warehouse, editable before running.
3. **Analyze** — run a SQL query; the app profiles every column for cardinality, null %, and scores each one for partition / cluster / bucket / index suitability.
4. **Ask AI** — paste a Gemini API key; the LLM receives both the column profile and your insight results, then gives structured optimization advice: recommended DDL, high-impact actions, and platform-specific gotchas.

---

## Running with Docker (recommended)

### Requirements
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (or Docker Engine + Compose)

### Start

```bash
cd performance_tuner
docker compose up --build
```

### URLs

| Service  | URL                        |
|----------|----------------------------|
| **App**  | http://localhost:3000      |
| **API**  | http://localhost:8000      |
| API docs | http://localhost:8000/docs |

The frontend proxies all `/api/` calls to the backend automatically.

---

## Running locally (development)

### Backend

```bash
cd performance_tuner
pip install -r requirements-api.txt
uvicorn api:app --reload --port 8000
```

> **SQL Server / Azure SQL** also require the [Microsoft ODBC Driver 18](https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server) installed on your machine.

### Frontend

```bash
cd performance_tuner/frontend
npm install
npm run dev
```

The Vite dev server runs at **http://localhost:5173** and proxies `/api/` to `localhost:8000`.

---

## How to use

### 1. Connect
Select your warehouse from the dropdown and fill in the credentials.  
All credentials stay in the browser — they are sent directly to your warehouse on each request and are never stored server-side.

### 2. Quick Insights
Pick an insight type, fill in optional parameters (schema, table name, lookback days).  
The SQL is auto-generated for your warehouse and is fully editable before running.  
Run as many insights as you like — all results are collected and automatically included when you ask for AI advice.

| Insight | What it surfaces |
|---------|-----------------|
| Most Queried Tables | Access counts, sequential vs index scans |
| Table Clustering / Indexes | Clustering keys, clustered indexes, index usage |
| Table Sizes & Access Counts | Row count, MB, read counts combined |
| Most Queried Columns | Column-level access (Snowflake) or column stats/sizes |
| Most Expensive Queries | Top queries by elapsed time + partition scan % |

### 3. Analyze Table
Enter a SQL query returning a representative sample of the table you want to optimise:

```sql
-- Snowflake example
SELECT * FROM analytics.fact_events LIMIT 200000;

-- Databricks example
SELECT * FROM hive_metastore.football.tracking WHERE match_id IN (1, 2, 3);
```

The app profiles each column: approximate unique count, null ratio, min/max, and scores for partition / cluster / bucket / index suitability.

### 4. Read the column table

| Column | Meaning |
|--------|---------|
| **Unique Values** | Approximate distinct count in the full table |
| **Cardinality** | LOW (<2% unique) / MED (2–10%) / HIGH (>10%) |
| **Partition ↑** | How suitable for `PARTITION BY` (higher = better) |
| **Cluster ↑** | How suitable for `CLUSTER BY` / sort key |
| **Bucket ↑** | How suitable for bucketing / banding |
| **Index ↑** | How suitable for a row-store index |
| **Best Use** | The highest-scoring role for that column |

Score colour guide: **green** ≥ 2.5 · **amber** ≥ 1.5 · **blue** ≥ 0.5 · **grey** < 0.5

### 5. Get AI advice
Paste a **Gemini API key** (get one free at [aistudio.google.com](https://aistudio.google.com)) and click **Get AI Advice**.  
The AI receives the full column profile **and** all collected insight results, then returns:
- Recommended data layout (partition / cluster / sort / bucket / index)
- Top 3 high-impact actions referencing actual usage patterns
- Platform-specific gotchas to avoid
- Sample DDL / SQL for your platform

---

## Supported warehouses

| Warehouse    | Required credentials |
|-------------|----------------------|
| Snowflake   | account, user, password, database, schema, warehouse |
| Databricks  | server hostname, HTTP path, access token |
| Azure SQL   | server, database, username, password |
| SQL Server  | server, database, username, password |
| PostgreSQL  | host, port, database, user, password |

---

## Project structure

```
performance_tuner/
├── advisor/             # Column profiling, scoring, simulation, platform recommendations
├── connectors/          # Warehouse adapters (Snowflake, Databricks, Azure SQL, SQL Server, PostgreSQL)
├── models.py            # Dataclass models (ColumnProfile, DatasetReport, …)
├── utils.py             # Shared utilities
├── api.py               # FastAPI backend (/api/profile, /api/run-query, /api/gemini-advice)
├── requirements-api.txt # Python dependencies
├── Dockerfile.backend   # Backend Docker image
├── docker-compose.yml   # One-command startup
├── config.yaml.example  # CLI config template (copy to config.yaml to use main.py)
└── frontend/            # React + Vite UI
    ├── src/
    │   ├── App.jsx      # Main UI (all components)
    │   ├── App.css      # Styles
    │   ├── queries.js   # Pre-built SQL templates per warehouse
    │   └── main.jsx     # Entry point
    ├── Dockerfile
    ├── nginx.conf
    └── vite.config.js
```

---

## Gemini models

| Model | Speed | Quality |
|-------|-------|---------|
| `gemini-1.5-flash` (default) | Fast | Good |
| `gemini-1.5-pro` | Slower | Better |
| `gemini-2.0-flash` | Fast | Best |

---

## CLI usage (Python only, no web UI)

The original `main.py` entry point still works for scripted or notebook workflows:

```python
from advisor import SmartAdvisor

advisor = SmartAdvisor.from_warehouse(
    storage="snowflake",
    auth={"account": "...", "user": "...", "password": "...",
          "database": "FOOTBALL", "schema": "PUBLIC", "warehouse": "COMPUTE_WH"},
    query="SELECT * FROM tracking WHERE match_id IN (1, 2)",
    platform="snowflake",
)
advisor.print_dataset_summary()
advisor.print_simulated_clustering_metadata(["match_id", "period"])
```

Copy `config.yaml.example` to `config.yaml` to use YAML-based connection settings.

---

## Security note
Credentials are passed from your browser to the backend on each request and used only to open a short-lived warehouse connection. They are not logged or stored. For production deployments, consider adding authentication middleware to the API.
