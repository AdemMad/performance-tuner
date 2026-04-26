from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ColumnProfile:
    column: str
    dtype: str
    row_count: int
    null_count: int
    null_ratio: float
    approx_unique_count: int
    unique_ratio: float
    min_value: Optional[Any]
    max_value: Optional[Any]
    is_temporal: bool
    looks_like_id: bool
    looks_like_metric: bool
    looks_like_zone: bool
    is_nested: bool
    partition_score: float
    clustering_score: float
    bucketing_score: float
    indexing_score: float
    notes: List[str] = field(default_factory=list)


@dataclass
class FileProfile:
    path: str
    file_size_bytes: Optional[int]
    file_size_mb: Optional[float]
    num_rows: int
    num_columns: int
    avg_row_size_bytes: Optional[float]
    num_row_groups: Optional[int]
    created_by: Optional[str]
    row_group_avg_rows: Optional[float]
    row_group_avg_mb: Optional[float]
    source_type: str = "parquet"  # "parquet" | "warehouse"


@dataclass
class CompactionRecommendation:
    current_file_size_mb: Optional[float]
    target_file_size_mb: int
    recommended_output_files: Optional[int]
    files_to_merge_for_target: Optional[int]
    message: str


@dataclass
class PlatformRecommendation:
    platform: str
    recommended_primary_technique: str
    recommended_secondary_techniques: List[str]
    recommended_partition_columns: List[str]
    recommended_cluster_columns: List[str]
    recommended_sort_order: List[str]
    recommended_bucket_columns: List[str]
    avoid_columns: List[str]
    sql_or_strategy: List[str]
    notes: List[str]


@dataclass
class SimulatedClusterFile:
    file_id: str
    stats: Dict[str, Dict[str, Any]]
    rows: str
    row_count: int


@dataclass
class SimulatedClusterMetadata:
    table: str
    clustering_columns: List[str]
    files: List[Dict[str, Any]]


@dataclass
class FilterCombinationAdvice:
    filter_columns: List[str]
    estimated_selectivity_label: str
    estimated_selectivity_score: float
    query_pattern_type: str
    layout_fit_score: float
    current_layout_assessment: str
    recommended_partition_columns: List[str]
    recommended_cluster_sort_order: List[str]
    recommended_bucket_columns: List[str]
    recommended_index_columns: List[str]
    derived_column_suggestions: List[str]
    warnings: List[str]
    reasoning: List[str]
    platform_recommendation: Optional[Dict[str, Any]] = None
    simulated_clustering_metadata: Optional[Dict[str, Any]] = None


@dataclass
class DatasetReport:
    file_profile: Dict[str, Any]
    compaction: Dict[str, Any]
    partition_candidates: List[str]
    clustering_candidates: List[str]
    bucketing_candidates: List[str]
    indexing_candidates: List[str]
    anti_patterns: List[str]
    columns: List[Dict[str, Any]]
    platform_summary: Optional[Dict[str, Any]] = None
