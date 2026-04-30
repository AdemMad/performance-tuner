# Data Warehouse Optimizer

A web app that connects to your data warehouse, profiles table columns, and provides AI-powered optimization advice using Google Gemini.

## What it does

1. **Connect** — enter credentials for Snowflake, Databricks, Azure SQL, SQL Server, or PostgreSQL.
2. **Analyze** — run a SQL query; the app profiles every column for cardinality, null %, and scores each one for partition / cluster / bucket / index suitability.
3. **Review** — see a ranked column table, platform-specific layout strategy, and detected anti-patterns.
4. **Ask AI** — paste a Gemini API key and get structured optimization advice: recommended DDL, high-impact actions, and platform-specific gotchas.

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
All fields stay in the browser — credentials are sent directly to your warehouse on each request and are never stored.

### 2. Write a query
Enter a SQL query that returns a representative sample of the table you want to optimise. A few thousand to a few hundred thousand rows is ideal:

```sql
-- Snowflake example
SELECT * FROM analytics.fact_events LIMIT 200000;

-- Databricks example
SELECT * FROM hive_metastore.football.tracking WHERE match_id IN (1, 2, 3);
```

### 3. Analyze
Click **Analyze Table**. The app:
- Fetches the sample from your warehouse
- Profiles each column: approximate unique count, null ratio, min/max
- Scores each column for partition, cluster, bucket, and index suitability
- Identifies anti-patterns (e.g. partitioning on a high-cardinality ID)

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
The AI receives the full column profile and returns:
- Recommended data layout (partition / cluster / sort / bucket / index)
- Top 3 high-impact actions
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
├── advisor/             # Column profiling, scoring, simulation logic
├── connectors/          # Warehouse connector adapters
├── models.py            # Dataclass models (ColumnProfile, DatasetReport, …)
├── utils.py             # Shared utilities
├── api.py               # FastAPI backend (NEW)
├── requirements-api.txt # Python dependencies (NEW)
├── Dockerfile.backend   # Backend Docker image (NEW)
├── docker-compose.yml   # Compose orchestration (NEW)
└── frontend/            # React app (NEW)
    ├── src/
    │   ├── App.jsx      # Main UI
    │   └── App.css      # Styles
    ├── Dockerfile
    └── nginx.conf
```

---

## Gemini models

| Model | Speed | Quality |
|-------|-------|---------|
| `gemini-1.5-flash` (default) | Fast | Good |
| `gemini-1.5-pro` | Slower | Better |
| `gemini-2.0-flash` | Fast | Best |

---

## Security note
Credentials are passed from your browser to the backend on each request and used only to open a short-lived warehouse connection. They are not logged or stored. For production use, consider adding authentication to the API.
