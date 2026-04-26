from __future__ import annotations

from typing import Any

import polars as pl


def bytes_to_mb(n: int) -> float:
    return n / (1024 * 1024)


def json_safe_value(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def is_orderable_dtype(dtype: pl.DataType) -> bool:
    return dtype in [
        pl.Int8, pl.Int16, pl.Int32, pl.Int64,
        pl.UInt8, pl.UInt16, pl.UInt32, pl.UInt64,
        pl.Float32, pl.Float64,
        pl.String, pl.Boolean,
        pl.Date, pl.Datetime, pl.Time,
    ]


def is_temporal_dtype(dtype: pl.DataType) -> bool:
    return dtype in [pl.Date, pl.Datetime, pl.Time]


def is_nested_dtype(dtype: pl.DataType) -> bool:
    dtype_str = str(dtype).lower()
    return "list" in dtype_str or "struct" in dtype_str or "array" in dtype_str


def supports_approx_n_unique(dtype: pl.DataType) -> bool:
    return not is_nested_dtype(dtype)


def is_temporal_name(col: str) -> bool:
    col = col.lower()
    tokens = ["date", "time", "timestamp", "clock", "period", "half", "season", "month", "week", "day"]
    return any(t in col for t in tokens)


def looks_like_id(col: str) -> bool:
    col = col.lower()
    return (
        col == "id"
        or col.endswith("_id")
        or "uuid" in col
        or col in {"match_id", "team_id", "player_id", "event_id"}
    )


def looks_like_metric(col: str) -> bool:
    col = col.lower()
    tokens = ["speed", "distance", "accel", "decel", "x", "y", "vx", "vy", "frame", "clock", "timestamp", "value"]
    return any(t == col or t in col for t in tokens)


def looks_like_zone(col: str) -> bool:
    col = col.lower()
    tokens = ["zone", "band", "bucket", "split", "segment", "tile", "bin", "grid"]
    return any(t in col for t in tokens)
