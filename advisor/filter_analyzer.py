from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from models import ColumnProfile

if TYPE_CHECKING:
    pass


class FilterAnalyzerMixin:
    """Filter-combination analysis logic."""

    _row_group_stats_cache: Optional[Dict[str, Any]]

    # ------------------------------------------------------------------
    # Query pattern
    # ------------------------------------------------------------------

    def _infer_query_pattern_type(self, selected: List[ColumnProfile]) -> str:
        if any(c.is_nested for c in selected):
            return "nested_or_semi_structured_filter"
        if any(c.looks_like_zone for c in selected) and any(c.looks_like_metric for c in selected):
            return "mixed_zone_plus_metric_filter"
        if any(c.looks_like_id for c in selected) and any(c.is_temporal for c in selected):
            return "entity_plus_time_filter"
        if all(c.looks_like_metric for c in selected):
            return "metric_range_or_granular_filter"
        if all(c.looks_like_id for c in selected):
            return "entity_lookup_filter"
        if all(c.is_temporal for c in selected):
            return "temporal_filter"
        return "mixed_filter"

    # ------------------------------------------------------------------
    # Selectivity estimation
    # ------------------------------------------------------------------

    def _estimate_combined_selectivity(self, selected: List[ColumnProfile]) -> Tuple[float, str]:
        components = []
        for c in selected:
            if c.is_nested:
                part = 0.1
            elif c.unique_ratio <= 0:
                part = 0.0
            else:
                part = min(1.0, max(0.05, -math.log10(max(c.unique_ratio, 1e-9)) / 6))
            components.append(part)

        combined = sum(components) / max(len(components), 1)

        if combined >= 0.75:
            label = "very_selective"
        elif combined >= 0.50:
            label = "moderately_selective"
        elif combined >= 0.25:
            label = "broad_to_moderate"
        else:
            label = "broad"

        return combined, label

    # ------------------------------------------------------------------
    # Layout fit assessment
    # ------------------------------------------------------------------

    def _assess_layout_fit(
        self,
        selected: List[ColumnProfile],
    ) -> Tuple[float, str, List[str], List[str]]:
        reasoning: List[str] = []
        warnings: List[str] = []
        score = 0.0

        low_card_cols = [c for c in selected if c.partition_score >= 2.0]
        cluster_cols  = [c for c in selected if c.clustering_score >= 2.0]
        bucket_cols   = [c for c in selected if c.bucketing_score >= 2.0]
        nested_cols   = [c for c in selected if c.is_nested]

        if low_card_cols:
            score += 2.0
            reasoning.append("At least one selected filter column is a strong partition candidate.")
        else:
            warnings.append("None of these filters look ideal for partitioning.")

        if cluster_cols:
            score += 2.0
            reasoning.append("At least one selected filter column would benefit from clustering/sort ordering.")

        if bucket_cols:
            score += 2.0
            reasoning.append("At least one selected filter column should be bucketed or banded before filtering.")

        if nested_cols:
            score -= 1.5
            warnings.append(
                "At least one selected column is nested/semi-structured; "
                "flatten it before relying on storage optimization."
            )

        for c in selected:
            lc = c.column.lower()
            if lc in {"x", "y", "player_x", "player_y", "ball_x", "ball_y"}:
                score -= 1.5
                warnings.append(f"{c.column} is a raw coordinate; use spatial zones instead.")
            if lc in {"frame_id", "timestamp", "gameclock", "time_seconds"}:
                score -= 1.2
                warnings.append(f"{c.column} is too granular raw time/frame; use bucketed splits.")
            if c.looks_like_id and c.unique_ratio > 0.2:
                warnings.append(f"{c.column} is very high-cardinality; partitioning on it would be weak.")

        if self._row_group_stats_cache:
            rg_avg_mb = self._row_group_stats_cache.get("row_group_avg_mb")
            if rg_avg_mb is not None:
                if rg_avg_mb < 8:
                    warnings.append("Row groups look small; metadata overhead and pruning may be suboptimal.")
                elif rg_avg_mb > 256:
                    warnings.append("Row groups look very large; range pruning may be coarser than ideal.")
                else:
                    reasoning.append("Row group size looks generally reasonable.")

        if score >= 4.5:
            assessment = "good_fit_if_layout_is_aligned"
        elif score >= 2.0:
            assessment = "partially_good_but_needs_better_layout"
        else:
            assessment = "poor_fit_for_current_raw_layout"

        return score, assessment, reasoning, warnings

    # ------------------------------------------------------------------
    # Per-aspect recommendations
    # ------------------------------------------------------------------

    def _recommend_partition_for_filter_set(self, selected: List[ColumnProfile]) -> List[str]:
        candidates = [
            c for c in selected
            if (
                not c.is_nested
                and c.partition_score >= 2.0
                and c.unique_ratio <= 0.05
                and c.approx_unique_count <= 1000
            )
        ]
        candidates = sorted(candidates, key=lambda x: (x.partition_score, -x.unique_ratio), reverse=True)
        return [c.column for c in candidates[:2]]

    def _recommend_sort_order_for_filter_set(self, selected: List[ColumnProfile]) -> List[str]:
        def key(c: ColumnProfile) -> Tuple[float, float, float]:
            priority = 0.0
            if c.partition_score >= 2.0:
                priority += 3.0
            if c.looks_like_id:
                priority += 2.0
            if c.is_temporal:
                priority += 2.0
            if c.is_nested:
                priority -= 3.0
            priority += c.clustering_score
            return (priority, -c.unique_ratio, -c.approx_unique_count)

        ordered = sorted(selected, key=key, reverse=True)
        return [c.column for c in ordered]

    def _recommend_bucketing_for_filter_set(
        self,
        selected: List[ColumnProfile],
    ) -> Tuple[List[str], List[str]]:
        bucket_cols: List[str] = []
        derived: List[str] = []

        for c in selected:
            lc = c.column.lower()

            if c.bucketing_score >= 2.0 and not c.is_nested:
                bucket_cols.append(c.column)

            if c.is_nested:
                derived.append(f"Flatten/explode nested column {c.column} before optimizing filters on it.")
            elif lc == "frame_id":
                derived.append("Create frame_bucket = frame_id // 500 (or 250/1000 depending on query pattern).")
            elif lc in {"gameclock", "timestamp", "time_seconds"}:
                derived.append("Create temporal splits/buckets, for example 5-minute bins or second buckets.")
            elif lc in {"x", "y", "player_x", "player_y", "ball_x", "ball_y"}:
                derived.append("Create spatial zones / pitch tiles instead of filtering raw coordinates.")
            elif "speed" in lc:
                derived.append("Create speed_band instead of filtering raw speed values.")
            elif "distance" in lc:
                derived.append("Create distance_band or split column for grouped filtering.")

        return sorted(set(bucket_cols)), derived

    def _recommend_indexing_for_filter_set(self, selected: List[ColumnProfile]) -> List[str]:
        return [
            c.column
            for c in sorted(selected, key=lambda x: x.indexing_score, reverse=True)
            if c.indexing_score >= 1.8 and not c.is_nested
        ]
