"""FastAPI backend — wraps SmartAdvisor and exposes Gemini advice."""
from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent))

from advisor import SmartAdvisor

app = FastAPI(title="Performance Tuner API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class ProfileRequest(BaseModel):
    storage: str
    auth: Dict[str, Any]
    query: str
    platform: Optional[str] = None
    sample_rows: int = 50_000


class RunQueryRequest(BaseModel):
    storage: str
    auth: Dict[str, Any]
    query: str
    limit: int = 500


class InsightResult(BaseModel):
    label: str
    rows: List[Dict[str, Any]]


class GeminiRequest(BaseModel):
    gemini_api_key: str
    profile: Optional[Dict[str, Any]] = None
    platform: str
    warehouse: str
    model: str = "gemini-1.5-flash"
    insight_results: List[InsightResult] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_plain(obj: Any) -> Any:
    """Recursively convert to JSON-serialisable Python primitives."""
    if isinstance(obj, dict):
        return {k: _to_plain(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_plain(v) for v in obj]
    if isinstance(obj, (int, float, str, bool, type(None))):
        return obj
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return str(obj)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/api/profile")
def profile_table(req: ProfileRequest) -> Dict[str, Any]:
    try:
        advisor = SmartAdvisor.from_warehouse(
            storage=req.storage,
            auth=req.auth,
            query=req.query,
            platform=req.platform,
            sample_rows=req.sample_rows,
        )
        report = advisor.profile_dataset()
        return _to_plain(asdict(report))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/run-query")
def run_query(req: RunQueryRequest) -> Dict[str, Any]:
    """Run an arbitrary SQL query and return raw results (for insight queries)."""
    try:
        from connectors import get_connector  # type: ignore
        connector = get_connector(req.storage, req.auth)
        df = connector.fetch(req.query)
        rows = _to_plain(df.head(req.limit).to_dicts())
        return {
            "columns": list(df.columns),
            "rows": rows,
            "row_count": len(rows),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/gemini-advice")
def gemini_advice(req: GeminiRequest) -> Dict[str, str]:
    try:
        import google.generativeai as genai  # type: ignore
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="google-generativeai not installed. Run: pip install google-generativeai",
        )

    try:
        genai.configure(api_key=req.gemini_api_key)
        model = genai.GenerativeModel(req.model)

        # --- Column profile section ---
        col_section = ""
        if req.profile:
            cols = req.profile.get("columns", [])
            col_lines = "\n".join(
                f"  - {c['column']} ({c['dtype']}): "
                f"~{c['approx_unique_count']:,} unique, "
                f"null {round(c['null_ratio'] * 100, 1)}%, "
                f"partition={c['partition_score']} cluster={c['clustering_score']} "
                f"bucket={c['bucketing_score']} index={c['indexing_score']}"
                for c in cols
            )
            ps = req.profile
            col_section = f"""
--- TABLE COLUMN PROFILE ---
{col_lines}

Advisor candidates:
  Partition: {ps.get('partition_candidates', [])}
  Cluster/Sort: {ps.get('clustering_candidates', [])}
  Bucket: {ps.get('bucketing_candidates', [])}
  Index: {ps.get('indexing_candidates', [])}
  Anti-patterns: {ps.get('anti_patterns', [])}
  Platform SQL hint: {ps.get('platform_summary', {}).get('sql_or_strategy', [])}"""

        # --- Insight results section ---
        insight_section = ""
        if req.insight_results:
            parts = []
            for ir in req.insight_results:
                rows_preview = json.dumps(ir.rows[:12], indent=2, default=str)
                parts.append(f"### {ir.label}\n{rows_preview}")
            insight_section = "\n--- USAGE INSIGHT QUERIES ---\n" + "\n\n".join(parts)

        prompt = f"""You are a senior data engineer specialising in {req.warehouse} ({req.platform}) optimisation.
{col_section}
{insight_section}

Based on the column profiles and/or usage insights above, provide concise, actionable optimisation advice:

## Recommended Data Layout
What to PARTITION BY, CLUSTER BY / sort, BUCKET, or INDEX — and why.
Reference cardinality, column size (avg_bytes), and actual access frequency from the insights.

## High-Impact Actions
Top 3 concrete steps. If insight data shows specific expensive queries or hot tables, address them directly.

## Watch Out For
Anti-patterns or gotchas specific to {req.platform}.

## Sample DDL / SQL
A short, realistic example for {req.platform} reflecting the recommendations.

Be direct and specific. Use markdown formatting."""

        response = model.generate_content(prompt)
        return {"advice": response.text}

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
