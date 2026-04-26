from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

import polars as pl

from models import SimulatedClusterFile, SimulatedClusterMetadata
import utils

if TYPE_CHECKING:
    pass


class SimulatorMixin:
    """
    Clustering simulation: sorts data by chosen columns, slices it into virtual
    'files', and computes per-file min/max statistics for each clustering column.

    This lets you visualise partition pruning — e.g. if you cluster on match_id
    and filter WHERE match_id IN (1, 2) the simulator will show that only the
    files whose stats overlap match_id=1 and match_id=2 need to be scanned.
    """

    target_file_size_mb: int
    _lazyframe: Optional[pl.LazyFrame]
    _schema: Any
    _num_rows: Optional[int]
    _file_size_bytes: Optional[int]

    # ------------------------------------------------------------------
    # Main public method
    # ------------------------------------------------------------------

    def simulate_clustering_metadata(
        self,
        clustering_columns: List[str],
        table_name: str = "simulated_table",
        rows_per_file: Optional[int] = None,
        target_file_size_mb: Optional[int] = None,
        include_row_range_column: Optional[str] = None,
        output_json_path: Optional[str | Path] = None,
    ) -> Dict[str, Any]:
        """
        Sort the sampled data by `clustering_columns`, split it into virtual
        files, and return per-file min/max stats.

        Args:
            clustering_columns:     Columns to sort and cluster by.
            table_name:             Label for the simulated table.
            rows_per_file:          Explicit rows per virtual file.
            target_file_size_mb:    Derive rows-per-file from this target.
            include_row_range_column: Show the min/max of this column in the
                                    row description (e.g. "frame_id 1→5000").
            output_json_path:       Optionally write the result to a JSON file.

        Returns:
            Dict matching SimulatedClusterMetadata schema.
        """
        self._ensure_loaded()
        assert self._lazyframe is not None
        assert self._schema is not None
        assert self._num_rows is not None

        missing = [c for c in clustering_columns if c not in self._schema]
        if missing:
            raise ValueError(f"Columns not found in dataset schema: {missing}")

        for c in clustering_columns:
            if utils.is_nested_dtype(self._schema[c]):
                raise ValueError(
                    f"Cannot simulate clustering on nested column '{c}' "
                    f"(dtype={self._schema[c]}). Flatten it first."
                )

        if include_row_range_column is not None and include_row_range_column not in self._schema:
            raise ValueError(f"Row range column not found in dataset schema: {include_row_range_column}")

        rows_per_file_final = self._resolve_rows_per_file(rows_per_file, target_file_size_mb)

        select_cols = list(dict.fromkeys(
            clustering_columns + ([include_row_range_column] if include_row_range_column else [])
        ))

        df = (
            self._lazyframe
            .select([pl.col(c) for c in select_cols])
            .sort(clustering_columns)
            .collect()
        )

        total_rows = df.height
        simulated_files: List[Dict[str, Any]] = []

        for idx, start in enumerate(range(0, total_rows, rows_per_file_final), start=1):
            end   = min(start + rows_per_file_final, total_rows)
            chunk = df.slice(start, end - start)

            stats: Dict[str, Dict[str, Any]] = {}
            for col in clustering_columns:
                col_stats = chunk.select(
                    [
                        pl.col(col).min().alias("min"),
                        pl.col(col).max().alias("max"),
                    ]
                ).to_dicts()[0]

                stats[col] = {
                    "min": utils.json_safe_value(col_stats["min"]),
                    "max": utils.json_safe_value(col_stats["max"]),
                }

            row_desc = self._build_simulated_row_description(
                chunk=chunk,
                include_row_range_column=include_row_range_column,
                fallback_start=start,
                fallback_end=end,
                clustering_columns=clustering_columns,
            )

            simulated_files.append(
                asdict(
                    SimulatedClusterFile(
                        file_id=f"file_{idx:03d}.parquet",
                        stats=stats,
                        rows=row_desc,
                        row_count=chunk.height,
                    )
                )
            )

        result = asdict(
            SimulatedClusterMetadata(
                table=table_name,
                clustering_columns=clustering_columns,
                files=simulated_files,
            )
        )

        if output_json_path is not None:
            Path(output_json_path).write_text(
                json.dumps(result, indent=2, default=str),
                encoding="utf-8",
            )

        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_rows_per_file(
        self,
        rows_per_file: Optional[int],
        target_file_size_mb: Optional[int],
    ) -> int:
        assert self._num_rows is not None

        if rows_per_file is not None and rows_per_file > 0:
            return rows_per_file

        if self._file_size_bytes is None:
            # For warehouse-sourced data there is no file; default to 100k rows/file
            return 100_000

        target_mb         = target_file_size_mb or self.target_file_size_mb
        avg_row_size_bytes = self._file_size_bytes / max(self._num_rows, 1)
        target_bytes      = target_mb * 1024 * 1024
        estimated_rows    = int(target_bytes / max(avg_row_size_bytes, 1))
        return max(1, estimated_rows)

    def _build_simulated_row_description(
        self,
        chunk: pl.DataFrame,
        include_row_range_column: Optional[str],
        fallback_start: int,
        fallback_end: int,
        clustering_columns: List[str],
    ) -> str:
        if include_row_range_column and include_row_range_column in chunk.columns:
            try:
                rv = chunk.select(
                    [
                        pl.col(include_row_range_column).min().alias("min_v"),
                        pl.col(include_row_range_column).max().alias("max_v"),
                    ]
                ).to_dicts()[0]

                min_v = utils.json_safe_value(rv["min_v"])
                max_v = utils.json_safe_value(rv["max_v"])

                extra_parts = []
                for c in clustering_columns:
                    if c == include_row_range_column:
                        continue
                    vals = chunk.select(
                        [
                            pl.col(c).min().alias("min_v"),
                            pl.col(c).max().alias("max_v"),
                        ]
                    ).to_dicts()[0]
                    cmin = utils.json_safe_value(vals["min_v"])
                    cmax = utils.json_safe_value(vals["max_v"])

                    if cmin == cmax:
                        extra_parts.append(f"{c}={cmin}")
                    else:
                        extra_parts.append(f"{c} {cmin}\u2192{cmax}")

                suffix = f" ({', '.join(extra_parts)})" if extra_parts else ""
                return f"{include_row_range_column} {min_v} \u2192 {max_v}{suffix}"
            except Exception:
                pass

        return f"row_index {fallback_start} \u2192 {fallback_end - 1}"

    # Implemented in core.py — declared here so type checkers are happy
    def _ensure_loaded(self) -> None:  # pragma: no cover
        raise NotImplementedError
