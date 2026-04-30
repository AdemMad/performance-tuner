from __future__ import annotations

import json
import math
import sys
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import polars as pl
import pyarrow.parquet as pq

# Allow imports from the project root when running this module directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models import (
    ColumnProfile,
    CompactionRecommendation,
    DatasetReport,
    FileProfile,
    FilterCombinationAdvice,
    PlatformRecommendation,
)
import utils

from .profiler       import ProfilerMixin
from .filter_analyzer import FilterAnalyzerMixin
from .simulator      import SimulatorMixin
from .platforms      import PlatformMixin


class SmartAdvisor(ProfilerMixin, FilterAnalyzerMixin, SimulatorMixin, PlatformMixin):
    """
    Storage-layout advisor for parquet files and data warehouses.

    Supported platforms: generic, databricks, snowflake, fabric,
                         sqlserver, azuresql, postgres

    Supported warehouse sources (via from_warehouse):
        snowflake, databricks, azure_sql, sqlserver, postgres

    Typical warehouse usage
    -----------------------
    advisor = SmartAdvisor.from_warehouse(
        storage="snowflake",
        auth={
            "account":   "xy12345.eu-west-1",
            "user":      "analytics_user",
            "password":  "secret",
            "database":  "FOOTBALL",
            "schema":    "PUBLIC",
            "warehouse": "COMPUTE_WH",
        },
        query="SELECT * FROM tracking WHERE match_id IN (1, 2)",
        platform="snowflake",
    )
    advisor.print_simulated_clustering_metadata(["match_id", "period"])
    """

    SUPPORTED_PLATFORMS = {
        "generic", "databricks", "snowflake",
        "fabric", "sqlserver", "azuresql", "postgres",
    }
    SUPPORTED_STORAGES = {
        "snowflake", "databricks", "azure_sql", "sqlserver", "postgres",
    }

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(
        self,
        sample_rows:         int = 250_000,
        target_file_size_mb: int = 200,
        platform:            str = "generic",
        platform_options:    Optional[Dict[str, Any]] = None,
        # internal – set via classmethods
        _path:               Optional[Path] = None,
        _dataframe:          Optional[pl.DataFrame] = None,
        _source_label:       str = "",
    ) -> None:
        plat = platform.lower().strip()
        if plat not in self.SUPPORTED_PLATFORMS:
            raise ValueError(
                f"Unsupported platform '{platform}'. "
                f"Supported: {sorted(self.SUPPORTED_PLATFORMS)}"
            )

        self.sample_rows         = sample_rows
        self.target_file_size_mb = target_file_size_mb
        self.platform            = plat
        self.platform_options    = platform_options or {}

        self._path         = _path
        self._dataframe    = _dataframe
        self._source_label = _source_label

        self._lazyframe:            Optional[pl.LazyFrame]       = None
        self._parquet_file:         Optional[pq.ParquetFile]     = None
        self._schema:               Optional[Dict[str, pl.DataType]] = None
        self._num_rows:             Optional[int]                = None
        self._file_size_bytes:      Optional[int]                = None
        self._column_profiles_cache: Optional[List[ColumnProfile]] = None
        self._row_group_stats_cache: Optional[Dict[str, Any]]   = None

    # ------------------------------------------------------------------
    # Classmethods (entry points)
    # ------------------------------------------------------------------

    @classmethod
    def from_parquet(
        cls,
        path:                str | Path,
        sample_rows:         int = 250_000,
        target_file_size_mb: int = 200,
        platform:            str = "generic",
        platform_options:    Optional[Dict[str, Any]] = None,
    ) -> "SmartAdvisor":
        """Create an advisor from a local Parquet file."""
        return cls(
            sample_rows=sample_rows,
            target_file_size_mb=target_file_size_mb,
            platform=platform,
            platform_options=platform_options,
            _path=Path(path),
        )

    @classmethod
    def from_dataframe(
        cls,
        df:                  pl.DataFrame,
        source_label:        str = "dataframe",
        sample_rows:         int = 250_000,
        target_file_size_mb: int = 200,
        platform:            str = "generic",
        platform_options:    Optional[Dict[str, Any]] = None,
    ) -> "SmartAdvisor":
        """Create an advisor from an already-loaded Polars DataFrame."""
        return cls(
            sample_rows=sample_rows,
            target_file_size_mb=target_file_size_mb,
            platform=platform,
            platform_options=platform_options,
            _dataframe=df,
            _source_label=source_label,
        )

    @classmethod
    def from_warehouse(
        cls,
        storage:             str,
        auth:                Dict[str, Any],
        query:               str,
        sample_rows:         int = 250_000,
        target_file_size_mb: int = 200,
        platform:            Optional[str] = None,
        platform_options:    Optional[Dict[str, Any]] = None,
    ) -> "SmartAdvisor":
        """
        Fetch a snapshot from a data warehouse and build an advisor from it.

        The query should return a *small, representative sample* of the table
        you want to analyse — for example filtering to a handful of match IDs.
        The advisor will profile the columns of that snapshot and simulate how
        clustering on any subset of columns would look across the full table.

        Args:
            storage:  One of "snowflake", "databricks", "azure_sql",
                      "sqlserver", "postgres".
            auth:     Connection credentials (see connectors/ for keys).
            query:    SQL query to fetch the sample, e.g.
                      "SELECT * FROM tracking WHERE match_id IN (1, 2)"
            platform: Override the platform for recommendations.
                      Defaults to the storage value when compatible.
            platform_options: Extra platform tuning options.
        """
        if storage not in cls.SUPPORTED_STORAGES:
            raise ValueError(
                f"Unsupported storage '{storage}'. "
                f"Supported: {sorted(cls.SUPPORTED_STORAGES)}"
            )

        # Import here to avoid hard dependency when using file-only mode
        from connectors import get_connector  # type: ignore[import]

        connector = get_connector(storage, auth)
        df        = connector.fetch(query)

        # Infer platform from storage when not explicitly set
        resolved_platform = platform or {
            "snowflake":  "snowflake",
            "databricks": "databricks",
            "azure_sql":  "azuresql",
            "sqlserver":  "sqlserver",
            "postgres":   "postgres",
        }.get(storage, "generic")

        return cls.from_dataframe(
            df=df,
            source_label=f"{storage}",
            sample_rows=sample_rows,
            target_file_size_mb=target_file_size_mb,
            platform=resolved_platform,
            platform_options=platform_options,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def profile_dataset(self) -> DatasetReport:
        self._ensure_loaded()

        file_profile = self._build_file_profile()
        columns      = self._profile_columns()
        compaction   = self._recommend_compaction(file_profile)
        (
            partition_candidates,
            clustering_candidates,
            bucketing_candidates,
            indexing_candidates,
        ) = self._collect_global_candidates(columns)
        anti_patterns = self._detect_anti_patterns(columns)

        platform_summary = asdict(
            self._build_platform_recommendation(
                partition_candidates=partition_candidates,
                clustering_candidates=clustering_candidates,
                bucketing_candidates=bucketing_candidates,
                sort_order=self._default_sort_order(columns),
                filter_columns=[],
            )
        )

        return DatasetReport(
            file_profile=asdict(file_profile),
            compaction=asdict(compaction),
            partition_candidates=partition_candidates,
            clustering_candidates=clustering_candidates,
            bucketing_candidates=bucketing_candidates,
            indexing_candidates=indexing_candidates,
            anti_patterns=anti_patterns,
            columns=[asdict(c) for c in columns],
            platform_summary=platform_summary,
        )

    def analyze_filter_combination(
        self,
        filter_columns:             List[str],
        simulate_metadata:          bool = False,
        simulation_table_name:      str = "simulated_table",
        simulation_rows_per_file:   Optional[int] = None,
        simulation_target_file_size_mb: Optional[int] = None,
        simulation_row_range_column: Optional[str] = None,
        simulation_clustering_columns: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        self._ensure_loaded()
        profiles = {c.column: c for c in self._profile_columns()}

        missing = [c for c in filter_columns if c not in profiles]
        if missing:
            raise ValueError(f"Columns not found in dataset schema: {missing}")

        selected             = [profiles[c] for c in filter_columns]
        query_pattern_type   = self._infer_query_pattern_type(selected)
        selectivity_score, selectivity_label = self._estimate_combined_selectivity(selected)
        layout_fit_score, current_layout_assessment, reasoning, warnings = self._assess_layout_fit(selected)

        recommended_partition_columns    = self._recommend_partition_for_filter_set(selected)
        recommended_cluster_sort_order   = self._recommend_sort_order_for_filter_set(selected)
        recommended_bucket_columns, derived_column_suggestions = self._recommend_bucketing_for_filter_set(selected)
        recommended_index_columns        = self._recommend_indexing_for_filter_set(selected)

        platform_reco = self._build_platform_recommendation(
            partition_candidates=recommended_partition_columns,
            clustering_candidates=[
                c for c in recommended_cluster_sort_order
                if c not in recommended_partition_columns
            ],
            bucketing_candidates=recommended_bucket_columns,
            sort_order=recommended_cluster_sort_order,
            filter_columns=filter_columns,
        )

        simulated_clustering_metadata = None
        if simulate_metadata:
            sim_cols = (
                simulation_clustering_columns
                or recommended_cluster_sort_order[:3]
                or filter_columns
            )
            simulated_clustering_metadata = self.simulate_clustering_metadata(
                clustering_columns=sim_cols,
                table_name=simulation_table_name,
                rows_per_file=simulation_rows_per_file,
                target_file_size_mb=simulation_target_file_size_mb,
                include_row_range_column=simulation_row_range_column,
            )

        advice = FilterCombinationAdvice(
            filter_columns=filter_columns,
            estimated_selectivity_label=selectivity_label,
            estimated_selectivity_score=round(selectivity_score, 4),
            query_pattern_type=query_pattern_type,
            layout_fit_score=round(layout_fit_score, 2),
            current_layout_assessment=current_layout_assessment,
            recommended_partition_columns=recommended_partition_columns,
            recommended_cluster_sort_order=recommended_cluster_sort_order,
            recommended_bucket_columns=recommended_bucket_columns,
            recommended_index_columns=recommended_index_columns,
            derived_column_suggestions=derived_column_suggestions,
            warnings=warnings,
            reasoning=reasoning,
            platform_recommendation=asdict(platform_reco),
            simulated_clustering_metadata=simulated_clustering_metadata,
        )
        return asdict(advice)

    # simulate_clustering_metadata is inherited from SimulatorMixin

    # ------------------------------------------------------------------
    # Print helpers
    # ------------------------------------------------------------------

    def print_dataset_summary(self) -> None:
        report = self.profile_dataset()

        print("\n=== FILE / SOURCE PROFILE ===")
        for k, v in report.file_profile.items():
            print(f"  {k}: {v}")

        print("\n=== COMPACTION ===")
        for k, v in report.compaction.items():
            print(f"  {k}: {v}")

        print("\n=== GLOBAL CANDIDATES ===")
        print("  partition_candidates:", report.partition_candidates)
        print("  clustering_candidates:", report.clustering_candidates)
        print("  bucketing_candidates:", report.bucketing_candidates)
        print("  indexing_candidates:", report.indexing_candidates)

        if report.platform_summary:
            print("\n=== PLATFORM SUMMARY ===")
            for k, v in report.platform_summary.items():
                print(f"  {k}: {v}")

        if report.anti_patterns:
            print("\n=== ANTI-PATTERNS ===")
            for x in report.anti_patterns:
                print(" -", x)

    def print_filter_analysis(
        self,
        filter_columns:    List[str],
        simulate_metadata: bool = False,
    ) -> None:
        result = self.analyze_filter_combination(
            filter_columns=filter_columns,
            simulate_metadata=simulate_metadata,
        )

        print("\n=== FILTER COMBINATION ANALYSIS ===")
        print("  Filters:", result["filter_columns"])
        print("  Pattern:", result["query_pattern_type"])
        print(
            "  Estimated selectivity:",
            result["estimated_selectivity_label"],
            result["estimated_selectivity_score"],
        )
        print("  Layout fit score:", result["layout_fit_score"])
        print("  Assessment:", result["current_layout_assessment"])

        print("\n  Recommended partition columns:", result["recommended_partition_columns"])
        print("  Recommended cluster/sort order:", result["recommended_cluster_sort_order"])
        print("  Recommended bucket columns:", result["recommended_bucket_columns"])
        print("  Recommended index columns:", result["recommended_index_columns"])

        if result["derived_column_suggestions"]:
            print("\n  Derived column suggestions:")
            for x in result["derived_column_suggestions"]:
                print("  -", x)

        if result["platform_recommendation"]:
            print("\n=== PLATFORM RECOMMENDATION ===")
            for k, v in result["platform_recommendation"].items():
                print(f"  {k}: {v}")

        if result["simulated_clustering_metadata"]:
            print("\n=== SIMULATED CLUSTERING METADATA ===")
            print(json.dumps(result["simulated_clustering_metadata"], indent=2, default=str))

        if result["warnings"]:
            print("\n  Warnings:")
            for x in result["warnings"]:
                print("  -", x)

        if result["reasoning"]:
            print("\n  Reasoning:")
            for x in result["reasoning"]:
                print("  -", x)

    def print_simulated_clustering_metadata(
        self,
        clustering_columns:     List[str],
        table_name:             str = "simulated_table",
        rows_per_file:          Optional[int] = None,
        target_file_size_mb:    Optional[int] = None,
        include_row_range_column: Optional[str] = None,
    ) -> None:
        result = self.simulate_clustering_metadata(
            clustering_columns=clustering_columns,
            table_name=table_name,
            rows_per_file=rows_per_file,
            target_file_size_mb=target_file_size_mb,
            include_row_range_column=include_row_range_column,
        )
        print(json.dumps(result, indent=2, default=str))

    def save_report_json(self, output_path: str | Path) -> None:
        report = self.profile_dataset()
        Path(output_path).write_text(
            json.dumps(asdict(report), indent=2, default=str),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # Internal: loading
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        if self._lazyframe is not None:
            return

        if self._dataframe is not None:
            self._load_from_dataframe(self._dataframe)
        elif self._path is not None:
            self._load_from_parquet(self._path)
        else:
            raise RuntimeError(
                "No data source configured. "
                "Use from_parquet(), from_dataframe(), or from_warehouse()."
            )

    def _load_from_parquet(self, path: Path) -> None:
        if not path.exists():
            raise FileNotFoundError(f"Parquet file not found: {path}")

        self._lazyframe    = pl.scan_parquet(str(path))
        self._parquet_file = pq.ParquetFile(path)

        if hasattr(self._lazyframe, "collect_schema"):
            self._schema = self._lazyframe.collect_schema()
        else:
            self._schema = self._lazyframe.schema

        self._num_rows        = self._parquet_file.metadata.num_rows
        self._file_size_bytes = path.stat().st_size
        self._row_group_stats_cache = self._extract_row_group_stats()

    def _load_from_dataframe(self, df: pl.DataFrame) -> None:
        self._lazyframe       = df.lazy()
        self._schema          = df.schema
        self._num_rows        = df.height
        self._file_size_bytes = None          # no physical file
        self._parquet_file    = None
        self._row_group_stats_cache = {}      # not applicable for warehouse data

    # ------------------------------------------------------------------
    # Internal: file/source profile
    # ------------------------------------------------------------------

    def _build_file_profile(self) -> FileProfile:
        assert self._schema is not None
        assert self._num_rows is not None

        if self._parquet_file is not None:
            # Parquet-backed source
            assert self._file_size_bytes is not None
            num_row_groups   = self._parquet_file.metadata.num_row_groups
            file_size_mb     = utils.bytes_to_mb(self._file_size_bytes)
            avg_row_size     = self._file_size_bytes / self._num_rows if self._num_rows else None
            rg_avg_rows      = self._num_rows / num_row_groups if num_row_groups else None
            rg_avg_mb        = file_size_mb / num_row_groups if num_row_groups else None

            return FileProfile(
                path=str(self._path),
                file_size_bytes=self._file_size_bytes,
                file_size_mb=round(file_size_mb, 2),
                num_rows=self._num_rows,
                num_columns=len(self._schema),
                avg_row_size_bytes=round(avg_row_size, 2) if avg_row_size is not None else None,
                num_row_groups=num_row_groups,
                created_by=getattr(self._parquet_file.metadata, "created_by", None),
                row_group_avg_rows=round(rg_avg_rows, 2) if rg_avg_rows else None,
                row_group_avg_mb=round(rg_avg_mb, 2) if rg_avg_mb else None,
                source_type="parquet",
            )
        else:
            # Warehouse / DataFrame source
            return FileProfile(
                path=self._source_label or "warehouse",
                file_size_bytes=None,
                file_size_mb=None,
                num_rows=self._num_rows,
                num_columns=len(self._schema),
                avg_row_size_bytes=None,
                num_row_groups=None,
                created_by=None,
                row_group_avg_rows=None,
                row_group_avg_mb=None,
                source_type="warehouse",
            )

    def _recommend_compaction(self, file_profile: FileProfile) -> CompactionRecommendation:
        if file_profile.source_type == "warehouse":
            return CompactionRecommendation(
                current_file_size_mb=None,
                target_file_size_mb=self.target_file_size_mb,
                recommended_output_files=None,
                files_to_merge_for_target=None,
                message=(
                    "Data sourced from a warehouse query; compaction does not apply. "
                    "Use platform-specific clustering/partitioning controls instead."
                ),
            )

        size_mb = file_profile.file_size_mb or 0.0
        target  = self.target_file_size_mb

        if size_mb <= 0:
            return CompactionRecommendation(
                current_file_size_mb=0.0,
                target_file_size_mb=target,
                recommended_output_files=1,
                files_to_merge_for_target=None,
                message="Unknown file size.",
            )

        if size_mb < target:
            files_to_merge = max(2, math.floor(target / max(size_mb, 1)))
            return CompactionRecommendation(
                current_file_size_mb=size_mb,
                target_file_size_mb=target,
                recommended_output_files=1,
                files_to_merge_for_target=files_to_merge,
                message=(
                    f"File is smaller than the {target}MB target. "
                    f"Compact ~{files_to_merge} sibling files into one target-sized file."
                ),
            )

        output_files = math.ceil(size_mb / target)
        return CompactionRecommendation(
            current_file_size_mb=size_mb,
            target_file_size_mb=target,
            recommended_output_files=output_files,
            files_to_merge_for_target=None,
            message=f"Rewrite into about {output_files} file(s) near {target}MB each.",
        )

    # ------------------------------------------------------------------
    # Internal: row group stats (parquet-only)
    # ------------------------------------------------------------------

    def _extract_row_group_stats(self) -> Dict[str, Any]:
        assert self._parquet_file is not None
        assert self._file_size_bytes is not None

        md  = self._parquet_file.metadata
        nrg = md.num_row_groups
        if nrg == 0:
            return {"row_group_avg_mb": None}

        file_mb = utils.bytes_to_mb(self._file_size_bytes)
        return {
            "num_row_groups":    nrg,
            "row_group_avg_mb":  round(file_mb / nrg, 2),
            "row_group_avg_rows": round(md.num_rows / nrg, 2) if md.num_rows else None,
        }
