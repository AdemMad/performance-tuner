from __future__ import annotations

from typing import Any, Callable, Dict, List, TYPE_CHECKING

from models import PlatformRecommendation

if TYPE_CHECKING:
    from models import ColumnProfile


class PlatformMixin:
    """Platform-specific recommendation logic."""

    platform: str
    platform_options: Dict[str, Any]
    target_file_size_mb: int

    # ------------------------------------------------------------------
    # Dispatcher
    # ------------------------------------------------------------------

    def _build_platform_recommendation(
        self,
        partition_candidates: List[str],
        clustering_candidates: List[str],
        bucketing_candidates: List[str],
        sort_order: List[str],
        filter_columns: List[str],
    ) -> PlatformRecommendation:
        dispatch: Dict[str, Callable[..., PlatformRecommendation]] = {
            "databricks": self._platform_databricks,
            "snowflake":  self._platform_snowflake,
            "fabric":     self._platform_fabric,
            "sqlserver":  self._platform_sqlserver,
            "azuresql":   self._platform_azuresql,
            "postgres":   self._platform_postgres,
        }
        fn = dispatch.get(self.platform, self._platform_generic)
        return fn(partition_candidates, clustering_candidates, bucketing_candidates, sort_order, filter_columns)

    # ------------------------------------------------------------------
    # Individual platforms
    # ------------------------------------------------------------------

    def _platform_generic(
        self,
        partition_candidates: List[str],
        clustering_candidates: List[str],
        bucketing_candidates: List[str],
        sort_order: List[str],
        filter_columns: List[str],
    ) -> PlatformRecommendation:
        sql = []
        if partition_candidates:
            sql.append(f"Partition using low-cardinality pruning columns like: {partition_candidates[:2]}")
        if sort_order:
            sql.append(f"Sort/cluster data using order: {sort_order[:4]}")
        if bucketing_candidates:
            sql.append(f"Create derived bucket/band columns for: {bucketing_candidates[:3]}")
        sql.append(f"Target file size around {self.target_file_size_mb}MB")

        return PlatformRecommendation(
            platform="generic",
            recommended_primary_technique="partition + sort/cluster",
            recommended_secondary_techniques=["bucketing", "compaction"],
            recommended_partition_columns=partition_candidates[:2],
            recommended_cluster_columns=clustering_candidates[:4],
            recommended_sort_order=sort_order[:5],
            recommended_bucket_columns=bucketing_candidates[:4],
            avoid_columns=self._infer_avoid_columns(partition_candidates, clustering_candidates),
            sql_or_strategy=sql,
            notes=["Generic recommendation without engine-specific optimizer features."],
        )

    def _platform_databricks(
        self,
        partition_candidates: List[str],
        clustering_candidates: List[str],
        bucketing_candidates: List[str],
        sort_order: List[str],
        filter_columns: List[str],
    ) -> PlatformRecommendation:
        use_liquid   = self.platform_options.get("use_liquid_clustering", True)
        use_zorder   = self.platform_options.get("use_zorder", False)
        max_parts    = self.platform_options.get("max_partition_columns", 2)

        partitions = partition_candidates[:max_parts]
        clusters   = clustering_candidates[:4]
        sql, notes = [], []

        if use_liquid:
            primary = "liquid_clustering"
            sql.append(f"Prefer Liquid Clustering on columns like: {clusters[:4] or sort_order[:4]}")
            notes.append("Liquid Clustering is usually better than over-partitioning on high-cardinality filters.")
        else:
            primary = "partition_plus_optimize"

        if partitions:
            sql.append(f"Keep partitioning light, e.g. PARTITIONED BY ({', '.join(partitions)})")
        if use_zorder and sort_order:
            sql.append(f"Use OPTIMIZE ... ZORDER BY ({', '.join(sort_order[:3])})")
            notes.append("Use Z-Ordering only when that fits your Databricks/Delta strategy and workload.")
        if bucketing_candidates:
            sql.append(f"Create derived bucket columns first for: {bucketing_candidates[:3]}")
        sql.append(f"Run file compaction / OPTIMIZE toward ~{self.target_file_size_mb}MB-ish target files.")

        return PlatformRecommendation(
            platform="databricks",
            recommended_primary_technique=primary,
            recommended_secondary_techniques=["light partitioning", "optimize/compaction", "derived bucketing"],
            recommended_partition_columns=partitions,
            recommended_cluster_columns=clusters,
            recommended_sort_order=sort_order[:5],
            recommended_bucket_columns=bucketing_candidates[:4],
            avoid_columns=self._infer_avoid_columns(partitions, clusters),
            sql_or_strategy=sql,
            notes=notes,
        )

    def _platform_snowflake(
        self,
        partition_candidates: List[str],
        clustering_candidates: List[str],
        bucketing_candidates: List[str],
        sort_order: List[str],
        filter_columns: List[str],
    ) -> PlatformRecommendation:
        cluster_cols = clustering_candidates[:4] or sort_order[:4]
        sql = []
        notes = [
            "Snowflake manages micro-partitions automatically.",
            "Do not think in lake-style manual folder partitioning first.",
        ]

        primary = "cluster_by" if cluster_cols else "micro_partition_pruning"

        if cluster_cols:
            sql.append(f"ALTER TABLE ... CLUSTER BY ({', '.join(cluster_cols[:3])})")
            sql.append(
                "-- Snowflake will automatically re-cluster over time; "
                "monitor clustering depth with SYSTEM$CLUSTERING_INFORMATION."
            )
        else:
            sql.append("Lean on natural micro-partition pruning first.")

        if bucketing_candidates:
            sql.append(f"Create derived bucket/band columns before loading, e.g. for: {bucketing_candidates[:3]}")
        if filter_columns:
            sql.append(f"For this workload, favor clustering around frequently filtered columns: {filter_columns[:3]}")

        return PlatformRecommendation(
            platform="snowflake",
            recommended_primary_technique=primary,
            recommended_secondary_techniques=["derived bucketing", "careful clustering depth monitoring"],
            recommended_partition_columns=[],
            recommended_cluster_columns=cluster_cols[:4],
            recommended_sort_order=sort_order[:5],
            recommended_bucket_columns=bucketing_candidates[:4],
            avoid_columns=self._infer_avoid_columns([], cluster_cols),
            sql_or_strategy=sql,
            notes=notes,
        )

    def _platform_fabric(
        self,
        partition_candidates: List[str],
        clustering_candidates: List[str],
        bucketing_candidates: List[str],
        sort_order: List[str],
        filter_columns: List[str],
    ) -> PlatformRecommendation:
        partitions = partition_candidates[:2]
        clusters   = clustering_candidates[:4]
        sql = []
        notes = [
            "Favor Delta/Lakehouse-friendly layout decisions.",
            "Keep partitioning practical; avoid tiny fragmented files.",
        ]

        if partitions:
            sql.append(f"Partition Lakehouse tables by low-cardinality columns like: {partitions}")
        if clusters:
            sql.append(f"Physically organize writes around filter order: {sort_order[:4]}")
        if bucketing_candidates:
            sql.append(f"Add derived band/zone/bucket columns for: {bucketing_candidates[:3]}")
        sql.append(f"Compact files toward ~{self.target_file_size_mb}MB targets.")

        return PlatformRecommendation(
            platform="fabric",
            recommended_primary_technique="delta_layout_optimization",
            recommended_secondary_techniques=["partitioning", "compaction", "derived bucketing"],
            recommended_partition_columns=partitions,
            recommended_cluster_columns=clusters,
            recommended_sort_order=sort_order[:5],
            recommended_bucket_columns=bucketing_candidates[:4],
            avoid_columns=self._infer_avoid_columns(partitions, clusters),
            sql_or_strategy=sql,
            notes=notes,
        )

    def _platform_sqlserver(
        self,
        partition_candidates: List[str],
        clustering_candidates: List[str],
        bucketing_candidates: List[str],
        sort_order: List[str],
        filter_columns: List[str],
    ) -> PlatformRecommendation:
        index_cols = clustering_candidates[:2] or sort_order[:2]
        partitions = partition_candidates[:1]
        sql = []
        notes = [
            "For analytics-heavy tables, consider Clustered Columnstore Index.",
            "For selective lookups, combine with supporting rowstore/nonclustered indexes where appropriate.",
        ]

        if partitions:
            sql.append(f"Use partition scheme/function on: {partitions[0]}")
        sql.append("Consider CLUSTERED COLUMNSTORE INDEX for large analytic fact-like tables.")
        if index_cols:
            sql.append(f"Consider supporting NONCLUSTERED INDEX on ({', '.join(index_cols)}) for selective filters.")
        if bucketing_candidates:
            sql.append(f"Precompute bucket/band columns before loading for: {bucketing_candidates[:3]}")

        return PlatformRecommendation(
            platform="sqlserver",
            recommended_primary_technique="clustered_columnstore_plus_partitioning",
            recommended_secondary_techniques=["nonclustered indexing", "partition scheme", "precomputed buckets"],
            recommended_partition_columns=partitions,
            recommended_cluster_columns=index_cols,
            recommended_sort_order=sort_order[:5],
            recommended_bucket_columns=bucketing_candidates[:4],
            avoid_columns=self._infer_avoid_columns(partitions, index_cols),
            sql_or_strategy=sql,
            notes=notes,
        )

    def _platform_azuresql(
        self,
        partition_candidates: List[str],
        clustering_candidates: List[str],
        bucketing_candidates: List[str],
        sort_order: List[str],
        filter_columns: List[str],
    ) -> PlatformRecommendation:
        index_cols = clustering_candidates[:2] or sort_order[:2]
        partitions = partition_candidates[:1]
        sql = []
        notes = [
            "Azure SQL shares the SQL Server engine; columnstore indexes apply equally.",
            "Consider Hyperscale tier for very large tables with mixed OLTP/OLAP patterns.",
            "Use Automatic Tuning for index recommendations in Azure SQL.",
        ]

        if partitions:
            sql.append(f"Apply table partitioning on low-cardinality column: {partitions[0]}")
        sql.append("CREATE CLUSTERED COLUMNSTORE INDEX cci ON dbo.YourTable;")
        if index_cols:
            sql.append(
                f"CREATE NONCLUSTERED INDEX nci ON dbo.YourTable ({', '.join(index_cols)}) "
                f"WITH (DATA_COMPRESSION = PAGE);"
            )
        if bucketing_candidates:
            sql.append(f"Precompute bucket/band columns before loading for: {bucketing_candidates[:3]}")

        return PlatformRecommendation(
            platform="azuresql",
            recommended_primary_technique="clustered_columnstore_plus_azure_tuning",
            recommended_secondary_techniques=["automatic tuning", "nonclustered index", "page compression"],
            recommended_partition_columns=partitions,
            recommended_cluster_columns=index_cols,
            recommended_sort_order=sort_order[:5],
            recommended_bucket_columns=bucketing_candidates[:4],
            avoid_columns=self._infer_avoid_columns(partitions, index_cols),
            sql_or_strategy=sql,
            notes=notes,
        )

    def _platform_postgres(
        self,
        partition_candidates: List[str],
        clustering_candidates: List[str],
        bucketing_candidates: List[str],
        sort_order: List[str],
        filter_columns: List[str],
    ) -> PlatformRecommendation:
        index_cols = clustering_candidates[:2] or sort_order[:2]
        partitions = partition_candidates[:1]
        sql = []
        notes = [
            "Postgres native partitioning is range or list based — avoid high-cardinality partition keys.",
            "BRIN indexes are excellent for naturally ordered columns (e.g., timestamps, sequential IDs).",
            "For analytics, consider pg_partman for automated partition management.",
        ]

        if partitions:
            col = partitions[0]
            sql.append(
                f"CREATE TABLE your_table (...) PARTITION BY RANGE ({col});\n"
                f"-- then: CREATE TABLE your_table_2024 PARTITION OF your_table\n"
                f"--       FOR VALUES FROM ('2024-01-01') TO ('2025-01-01');"
            )
        if index_cols:
            sql.append(f"CREATE INDEX ON your_table USING BRIN ({index_cols[0]});  -- for ordered columns")
            sql.append(f"CREATE INDEX ON your_table ({', '.join(index_cols)});     -- for selective lookup")
        if bucketing_candidates:
            sql.append(f"Add computed bucket columns before loading for: {bucketing_candidates[:3]}")
        sql.append("CLUSTER your_table USING index_name;  -- physically reorder rows (one-time, blocking)")

        return PlatformRecommendation(
            platform="postgres",
            recommended_primary_technique="range_partitioning_plus_brin",
            recommended_secondary_techniques=["btree index", "CLUSTER", "pg_partman", "computed columns"],
            recommended_partition_columns=partitions,
            recommended_cluster_columns=index_cols,
            recommended_sort_order=sort_order[:5],
            recommended_bucket_columns=bucketing_candidates[:4],
            avoid_columns=self._infer_avoid_columns(partitions, index_cols),
            sql_or_strategy=sql,
            notes=notes,
        )

    # ------------------------------------------------------------------
    # Shared helper (must be available on the final class)
    # ------------------------------------------------------------------

    def _infer_avoid_columns(self, partition_cols: List[str], cluster_cols: List[str]) -> List[str]:
        columns = self._profile_columns()  # type: ignore[attr-defined]
        chosen = set(partition_cols) | set(cluster_cols)
        avoid = []
        for c in columns:
            lc = c.column.lower()
            if c.column in chosen:
                continue
            if c.is_nested:
                avoid.append(c.column)
            elif lc in {"x", "y", "player_x", "player_y", "ball_x", "ball_y", "frame_id", "timestamp", "gameclock"}:
                avoid.append(c.column)
        return sorted(set(avoid))[:10]
