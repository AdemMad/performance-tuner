from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

import polars as pl

from models import ColumnProfile
import utils

if TYPE_CHECKING:
    pass


class ProfilerMixin:
    """Column profiling and scoring logic."""

    sample_rows: int
    _lazyframe: Optional[pl.LazyFrame]
    _schema: Any
    _num_rows: Optional[int]
    _column_profiles_cache: Optional[List[ColumnProfile]]

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def _profile_columns(self) -> List[ColumnProfile]:
        if self._column_profiles_cache is not None:
            return self._column_profiles_cache

        assert self._lazyframe is not None
        assert self._schema is not None
        assert self._num_rows is not None

        sample_n = min(self.sample_rows, self._num_rows)
        lf_sample = self._lazyframe.slice(0, sample_n)

        columns: List[ColumnProfile] = []

        for col_name, dtype in self._schema.items():
            is_nested = utils.is_nested_dtype(dtype)

            exprs = [pl.col(col_name).null_count().alias("null_count")]

            if utils.supports_approx_n_unique(dtype):
                exprs.append(pl.col(col_name).approx_n_unique().alias("approx_unique_count"))
            else:
                exprs.append(pl.lit(None).alias("approx_unique_count"))

            if utils.is_orderable_dtype(dtype) and not is_nested:
                exprs += [
                    pl.col(col_name).min().alias("min_value"),
                    pl.col(col_name).max().alias("max_value"),
                ]
            else:
                exprs += [pl.lit(None).alias("min_value"), pl.lit(None).alias("max_value")]

            try:
                stats = lf_sample.select(exprs).collect().to_dicts()[0]
                error_note = None
            except Exception as e:
                stats = {
                    "null_count": 0,
                    "approx_unique_count": None,
                    "min_value": None,
                    "max_value": None,
                }
                error_note = f"Column-level profiling fallback used due to: {type(e).__name__}: {e}"

            null_count = int(stats["null_count"] or 0)
            approx_unique_sample = stats["approx_unique_count"]

            if approx_unique_sample is None:
                approx_unique_total = 0
                unique_ratio = 0.0
            else:
                approx_unique_sample = int(approx_unique_sample)
                if sample_n == self._num_rows:
                    approx_unique_total = approx_unique_sample
                else:
                    approx_unique_total = min(
                        self._num_rows,
                        int(approx_unique_sample * math.sqrt(self._num_rows / max(sample_n, 1))),
                    )
                unique_ratio = approx_unique_total / max(self._num_rows, 1)

            null_ratio = null_count / max(sample_n, 1)

            is_temporal   = utils.is_temporal_name(col_name) or utils.is_temporal_dtype(dtype)
            looks_id      = utils.looks_like_id(col_name)
            looks_metric  = utils.looks_like_metric(col_name)
            looks_zone    = utils.looks_like_zone(col_name)

            partition_score, clustering_score, bucketing_score, indexing_score, notes = self._score_column(
                col_name=col_name,
                dtype=dtype,
                approx_unique_count=approx_unique_total,
                unique_ratio=unique_ratio,
                null_ratio=null_ratio,
                is_temporal=is_temporal,
                looks_like_id=looks_id,
                looks_like_metric=looks_metric,
                looks_like_zone=looks_zone,
            )

            if is_nested:
                partition_score  = 0.0
                clustering_score = max(clustering_score, 0.5)
                bucketing_score  = 0.0
                indexing_score   = 0.0
                notes.append("Nested column detected; skip raw cardinality-based optimization advice.")
                notes.append("If queried often, flatten/explode this column into a child tabular dataset first.")

            if error_note:
                notes.append(error_note)

            columns.append(
                ColumnProfile(
                    column=col_name,
                    dtype=str(dtype),
                    row_count=self._num_rows,
                    null_count=null_count,
                    null_ratio=round(null_ratio, 6),
                    approx_unique_count=approx_unique_total,
                    unique_ratio=round(unique_ratio, 6),
                    min_value=stats["min_value"],
                    max_value=stats["max_value"],
                    is_temporal=is_temporal,
                    looks_like_id=looks_id,
                    looks_like_metric=looks_metric,
                    looks_like_zone=looks_zone,
                    is_nested=is_nested,
                    partition_score=round(partition_score, 2),
                    clustering_score=round(clustering_score, 2),
                    bucketing_score=round(bucketing_score, 2),
                    indexing_score=round(indexing_score, 2),
                    notes=notes,
                )
            )

        self._column_profiles_cache = sorted(
            columns,
            key=lambda x: max(x.partition_score, x.clustering_score, x.bucketing_score, x.indexing_score),
            reverse=True,
        )
        return self._column_profiles_cache

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _score_column(
        self,
        col_name: str,
        dtype: pl.DataType,
        approx_unique_count: int,
        unique_ratio: float,
        null_ratio: float,
        is_temporal: bool,
        looks_like_id: bool,
        looks_like_metric: bool,
        looks_like_zone: bool,
    ) -> Tuple[float, float, float, float, List[str]]:
        notes: List[str] = []

        if utils.is_nested_dtype(dtype):
            notes.append("Nested type is not a good raw partition/filter/index candidate.")
            return 0.0, 0.5, 0.0, 0.0, notes

        partition_score  = 0.0
        clustering_score = 0.0
        bucketing_score  = 0.0
        indexing_score   = 0.0

        is_low_card    = approx_unique_count <= 200 or unique_ratio <= 0.02
        is_medium_card = 200 < approx_unique_count <= 10_000
        is_high_card   = approx_unique_count > 10_000 or unique_ratio > 0.10

        # --- partition ---
        if is_temporal:
            partition_score += 2.5
            notes.append("Temporal-style column can prune partitions well.")
        if looks_like_zone:
            partition_score += 2.0
            notes.append("Derived zone/band style column is good for partition pruning.")
        if is_low_card:
            partition_score += 1.5
            notes.append("Low-cardinality column can be a partition candidate.")
        if is_high_card:
            partition_score -= 2.5
            notes.append("Too granular for partitioning.")
        if looks_like_id and is_high_card:
            partition_score -= 2.0
            notes.append("High-cardinality ID is usually a bad partition key.")
        if null_ratio > 0.5:
            partition_score -= 0.5
            notes.append("High null ratio weakens partition usefulness.")

        # --- clustering ---
        if is_temporal:
            clustering_score += 1.5
            notes.append("Temporal ordering helps range pruning.")
        if looks_like_id:
            clustering_score += 1.5
            notes.append("ID may benefit from clustering/sort if filtered or joined often.")
        if is_medium_card or is_high_card:
            clustering_score += 1.3
        if looks_like_zone:
            clustering_score += 0.5

        # --- bucketing ---
        if looks_like_metric and is_high_card:
            bucketing_score += 2.2
            notes.append("High-cardinality metric likely needs bucketing/banding.")
        if is_temporal and is_high_card:
            bucketing_score += 2.0
            notes.append("High-cardinality temporal field likely needs bucketing.")
        if looks_like_id and is_high_card:
            bucketing_score += 1.0

        # --- indexing ---
        if looks_like_id:
            indexing_score += 2.5
            notes.append("Likely join/filter key for row-store indexes.")
        if is_temporal:
            indexing_score += 1.2
        if looks_like_zone:
            indexing_score += 0.5
        if looks_like_metric and is_high_card:
            indexing_score -= 0.4

        # --- domain overrides ---
        lc = col_name.lower()
        if lc in {"frame_id", "gameclock", "timestamp", "time_seconds"}:
            partition_score  -= 1.5
            clustering_score += 2.0
            bucketing_score  += 2.5
            notes.append("Raw frame/time column: better bucket + sort than partition.")

        if lc in {"x", "y", "player_x", "player_y", "ball_x", "ball_y"}:
            partition_score -= 1.5
            bucketing_score += 2.5
            notes.append("Raw coordinate: create spatial zones instead of filtering raw values.")

        return (
            max(partition_score, 0.0),
            max(clustering_score, 0.0),
            max(bucketing_score, 0.0),
            max(indexing_score, 0.0),
            notes,
        )

    # ------------------------------------------------------------------
    # Global candidate lists
    # ------------------------------------------------------------------

    def _collect_global_candidates(
        self,
        columns: List[ColumnProfile],
    ) -> Tuple[List[str], List[str], List[str], List[str]]:
        partition_candidates  = [c.column for c in columns if c.partition_score  >= 2.5 and not c.is_nested]
        clustering_candidates = [c.column for c in columns if c.clustering_score >= 2.2 and not c.is_nested]
        bucketing_candidates  = [c.column for c in columns if c.bucketing_score  >= 2.2 and not c.is_nested]
        indexing_candidates   = [c.column for c in columns if c.indexing_score   >= 2.2 and not c.is_nested]
        return partition_candidates, clustering_candidates, bucketing_candidates, indexing_candidates

    def _detect_anti_patterns(self, columns: List[ColumnProfile]) -> List[str]:
        anti: List[str] = []
        for c in columns:
            lc = c.column.lower()
            if c.is_nested:
                anti.append(f"Do not optimize directly on nested column {c.column}; flatten it first.")
            if lc in {"frame_id", "timestamp", "gameclock"}:
                anti.append(f"Avoid partitioning on {c.column}; bucket and sort it instead.")
            if lc in {"x", "y", "player_x", "player_y", "ball_x", "ball_y"}:
                anti.append(f"Avoid raw filtering on {c.column}; derive spatial zones first.")
            if c.looks_like_id and c.unique_ratio > 0.1:
                anti.append(f"Avoid partitioning on high-cardinality ID column {c.column}.")
        return sorted(set(anti))

    def _default_sort_order(self, columns: List[ColumnProfile]) -> List[str]:
        ordered = sorted(
            [c for c in columns if not c.is_nested],
            key=lambda c: (
                c.partition_score >= 2.0,
                c.looks_like_id,
                c.is_temporal,
                c.clustering_score,
                -c.unique_ratio,
            ),
            reverse=True,
        )
        return [c.column for c in ordered[:8]]
