/**
 * Pre-built insight queries — one SQL function per warehouse per insight type.
 * Each function receives a params object and returns a ready-to-run SQL string.
 */

export const INSIGHT_TYPES = [
  { id: 'most_queried_tables',    label: 'Most Queried Tables' },
  { id: 'table_clustering',       label: 'Table Clustering / Indexes' },
  { id: 'tables_with_size',       label: 'Table Sizes & Access Counts' },
  { id: 'most_queried_columns',   label: 'Most Queried Columns' },
  { id: 'most_expensive_queries', label: 'Most Expensive Queries' },
]

/** Parameter definitions per insight type — shown as form inputs */
export const INSIGHT_PARAMS = {
  most_queried_tables: [
    { key: 'days', label: 'Lookback (days)', default: '30' },
  ],
  table_clustering: [
    { key: 'schema', label: 'Schema / Dataset', default: '' },
  ],
  tables_with_size: [
    { key: 'schema', label: 'Schema (leave blank for current)', default: '' },
  ],
  most_queried_columns: [
    { key: 'schema', label: 'Schema',       default: '' },
    { key: 'table',  label: 'Table name',   default: '' },
    { key: 'days',   label: 'Lookback (days)', default: '30' },
  ],
  most_expensive_queries: [
    { key: 'schema', label: 'Schema (optional)', default: '' },
    { key: 'days',   label: 'Lookback (days)',   default: '7' },
  ],
}

// ---------------------------------------------------------------------------
// SQL templates — indexed by [insightType][warehouseKey]
// ---------------------------------------------------------------------------

const SQL = {

  // ── Most Queried Tables ────────────────────────────────────────────────────
  most_queried_tables: {

    snowflake: ({ days = 30 }) => `\
-- Most queried tables — last ${days} days
-- Requires SNOWFLAKE.ACCOUNT_USAGE (Enterprise tier; up to 3 h lag)
SELECT
    obj.value:objectName::STRING            AS table_name,
    COUNT(*)                                AS access_count,
    MAX(h.query_start_time)::DATE           AS last_accessed
FROM snowflake.account_usage.access_history h,
     LATERAL FLATTEN(input => base_objects_accessed) obj
WHERE obj.value:objectDomain = 'Table'
  AND h.query_start_time >= DATEADD('day', -${days}, CURRENT_TIMESTAMP())
GROUP BY 1
ORDER BY 2 DESC
LIMIT 25;`,

    databricks: ({ days = 30 }) => `\
-- Most queried tables — last ${days} days (Unity Catalog required)
SELECT
    statement_type,
    COUNT(*)                                AS query_count,
    ROUND(AVG(total_duration_ms) / 1000, 2) AS avg_seconds,
    MAX(created_at)::DATE                   AS last_seen
FROM system.query.history
WHERE created_at >= CURRENT_TIMESTAMP() - INTERVAL ${days} DAYS
  AND statement_type IN ('SELECT', 'INSERT', 'MERGE', 'UPDATE', 'DELETE')
GROUP BY 1
ORDER BY 2 DESC
LIMIT 25;`,

    azure_sql: () => `\
-- Most accessed tables (stats since last SQL Server restart)
SELECT TOP 25
    OBJECT_SCHEMA_NAME(ius.object_id)                       AS schema_name,
    OBJECT_NAME(ius.object_id)                              AS table_name,
    SUM(ius.user_seeks + ius.user_scans + ius.user_lookups) AS total_reads,
    SUM(ius.user_updates)                                   AS total_writes
FROM sys.dm_db_index_usage_stats ius
WHERE database_id = DB_ID()
  AND OBJECT_NAME(ius.object_id) IS NOT NULL
GROUP BY ius.object_id
ORDER BY total_reads DESC;`,

    sqlserver: () => `\
-- Most accessed tables (stats since last SQL Server restart)
SELECT TOP 25
    OBJECT_SCHEMA_NAME(ius.object_id)                       AS schema_name,
    OBJECT_NAME(ius.object_id)                              AS table_name,
    SUM(ius.user_seeks + ius.user_scans + ius.user_lookups) AS total_reads,
    SUM(ius.user_updates)                                   AS total_writes
FROM sys.dm_db_index_usage_stats ius
WHERE database_id = DB_ID()
  AND OBJECT_NAME(ius.object_id) IS NOT NULL
GROUP BY ius.object_id
ORDER BY total_reads DESC;`,

    postgres: () => `\
-- Most accessed tables (cumulative since last pg_stat reset)
SELECT
    schemaname,
    relname                         AS table_name,
    seq_scan + idx_scan             AS total_accesses,
    seq_scan                        AS sequential_scans,
    idx_scan                        AS index_scans,
    n_live_tup                      AS live_rows,
    last_autoanalyze::DATE          AS last_analyzed
FROM pg_stat_user_tables
ORDER BY total_accesses DESC
LIMIT 25;`,
  },

  // ── Table Clustering / Indexes ─────────────────────────────────────────────
  table_clustering: {

    snowflake: ({ schema = '' }) => `\
-- Clustering keys and table sizes
SELECT
    table_name,
    clustering_key,
    row_count,
    ROUND(bytes / 1048576.0, 2)     AS size_mb,
    created::DATE                   AS created,
    last_altered::DATE              AS last_altered
FROM information_schema.tables
WHERE table_schema = ${schema ? `'${schema.toUpperCase()}'` : 'CURRENT_SCHEMA()'}
  AND table_type = 'BASE TABLE'
ORDER BY bytes DESC NULLS LAST
LIMIT 25;`,

    databricks: ({ schema = 'default' }) => `\
-- Delta table storage format and metadata
SELECT
    table_name,
    table_type,
    data_source_format,
    created,
    last_altered
FROM system.information_schema.tables
WHERE table_schema = '${schema || 'default'}'
ORDER BY table_name
LIMIT 25;`,

    azure_sql: () => `\
-- Clustered indexes per table with key columns
SELECT
    s.name                                      AS schema_name,
    t.name                                      AS table_name,
    i.name                                      AS clustered_index,
    STRING_AGG(c.name, ', ')
        WITHIN GROUP (ORDER BY ic.key_ordinal)  AS key_columns,
    ps.row_count,
    ROUND(ps.used_page_count * 8.0 / 1024, 2)  AS used_mb
FROM sys.tables t
JOIN sys.schemas s       ON t.schema_id = s.schema_id
JOIN sys.indexes i       ON t.object_id = i.object_id AND i.type = 1
JOIN sys.index_columns ic ON i.object_id = ic.object_id
                         AND i.index_id  = ic.index_id
JOIN sys.columns c       ON ic.object_id = c.object_id
                         AND ic.column_id = c.column_id
JOIN sys.dm_db_partition_stats ps
    ON t.object_id = ps.object_id AND ps.index_id <= 1
WHERE t.is_ms_shipped = 0
GROUP BY s.name, t.name, i.name, ps.row_count, ps.used_page_count
ORDER BY used_mb DESC;`,

    sqlserver: () => `\
-- Clustered indexes per table with key columns
SELECT
    s.name                                      AS schema_name,
    t.name                                      AS table_name,
    i.name                                      AS clustered_index,
    STRING_AGG(c.name, ', ')
        WITHIN GROUP (ORDER BY ic.key_ordinal)  AS key_columns,
    ps.row_count,
    ROUND(ps.used_page_count * 8.0 / 1024, 2)  AS used_mb
FROM sys.tables t
JOIN sys.schemas s       ON t.schema_id = s.schema_id
JOIN sys.indexes i       ON t.object_id = i.object_id AND i.type = 1
JOIN sys.index_columns ic ON i.object_id = ic.object_id
                         AND i.index_id  = ic.index_id
JOIN sys.columns c       ON ic.object_id = c.object_id
                         AND ic.column_id = c.column_id
JOIN sys.dm_db_partition_stats ps
    ON t.object_id = ps.object_id AND ps.index_id <= 1
WHERE t.is_ms_shipped = 0
GROUP BY s.name, t.name, i.name, ps.row_count, ps.used_page_count
ORDER BY used_mb DESC;`,

    postgres: ({ schema = 'public' }) => `\
-- Index usage and clustering info for schema '${schema || 'public'}'
SELECT
    t.relname                       AS table_name,
    i.relname                       AS index_name,
    ix.indisprimary                 AS is_primary,
    ix.indisunique                  AS is_unique,
    ix.indisclustered               AS is_clustered,
    COALESCE(s.idx_scan, 0)        AS index_scans,
    pg_size_pretty(pg_relation_size(i.oid)) AS index_size,
    array_to_string(ARRAY(
        SELECT pg_get_indexdef(ix.indexrelid, k + 1, true)
        FROM generate_subscripts(ix.indkey, 1) AS k ORDER BY k
    ), ', ')                        AS indexed_columns
FROM pg_index ix
JOIN pg_class t  ON t.oid = ix.indrelid
JOIN pg_class i  ON i.oid = ix.indexrelid
JOIN pg_namespace ns ON t.relnamespace = ns.oid
LEFT JOIN pg_stat_user_indexes s ON s.indexrelid = ix.indexrelid
WHERE t.relkind = 'r'
  AND ns.nspname = '${schema || 'public'}'
ORDER BY COALESCE(s.idx_scan, 0) DESC
LIMIT 25;`,
  },

  // ── Tables with Size ───────────────────────────────────────────────────────
  tables_with_size: {

    snowflake: ({ schema = '' }) => `\
-- Table sizes, row counts and clustering keys
SELECT
    table_name,
    row_count,
    ROUND(bytes / 1048576.0, 2)     AS size_mb,
    clustering_key,
    created::DATE                   AS created,
    last_altered::DATE              AS last_altered
FROM information_schema.tables
WHERE table_schema = ${schema ? `'${schema.toUpperCase()}'` : 'CURRENT_SCHEMA()'}
  AND table_type = 'BASE TABLE'
ORDER BY bytes DESC NULLS LAST
LIMIT 25;`,

    databricks: ({ schema = 'default' }) => `\
-- Table list for schema '${schema || 'default'}' (Unity Catalog)
SELECT
    table_name,
    table_type,
    data_source_format,
    created,
    last_altered
FROM system.information_schema.tables
WHERE table_schema = '${schema || 'default'}'
ORDER BY last_altered DESC
LIMIT 25;`,

    azure_sql: () => `\
-- Table sizes with read access counts
SELECT TOP 25
    s.name                                              AS schema_name,
    t.name                                              AS table_name,
    p.rows                                              AS row_count,
    ROUND(SUM(a.total_pages) * 8.0 / 1024, 2)         AS total_mb,
    ROUND(SUM(a.used_pages)  * 8.0 / 1024, 2)         AS used_mb,
    ISNULL(SUM(ius.user_seeks + ius.user_scans
               + ius.user_lookups), 0)                 AS total_reads
FROM sys.tables t
JOIN sys.schemas s ON t.schema_id = s.schema_id
JOIN sys.indexes i ON t.object_id = i.object_id AND i.index_id <= 1
JOIN sys.partitions p ON i.object_id = p.object_id AND i.index_id = p.index_id
JOIN sys.allocation_units a ON p.partition_id = a.container_id
LEFT JOIN sys.dm_db_index_usage_stats ius
    ON t.object_id = ius.object_id AND ius.database_id = DB_ID()
WHERE t.is_ms_shipped = 0
GROUP BY s.name, t.name, p.rows
ORDER BY total_reads DESC;`,

    sqlserver: () => `\
-- Table sizes with read access counts
SELECT TOP 25
    s.name                                              AS schema_name,
    t.name                                              AS table_name,
    p.rows                                              AS row_count,
    ROUND(SUM(a.total_pages) * 8.0 / 1024, 2)         AS total_mb,
    ROUND(SUM(a.used_pages)  * 8.0 / 1024, 2)         AS used_mb,
    ISNULL(SUM(ius.user_seeks + ius.user_scans
               + ius.user_lookups), 0)                 AS total_reads
FROM sys.tables t
JOIN sys.schemas s ON t.schema_id = s.schema_id
JOIN sys.indexes i ON t.object_id = i.object_id AND i.index_id <= 1
JOIN sys.partitions p ON i.object_id = p.object_id AND i.index_id = p.index_id
JOIN sys.allocation_units a ON p.partition_id = a.container_id
LEFT JOIN sys.dm_db_index_usage_stats ius
    ON t.object_id = ius.object_id AND ius.database_id = DB_ID()
WHERE t.is_ms_shipped = 0
GROUP BY s.name, t.name, p.rows
ORDER BY total_reads DESC;`,

    postgres: ({ schema = '' }) => `\
-- Table sizes and access counts${schema ? ` for schema '${schema}'` : ''}
SELECT
    st.schemaname,
    st.relname                                                  AS table_name,
    st.seq_scan + st.idx_scan                                   AS total_accesses,
    st.n_live_tup                                               AS row_count,
    pg_size_pretty(pg_total_relation_size(
        quote_ident(st.schemaname)||'.'||quote_ident(st.relname))) AS total_size,
    ROUND(pg_total_relation_size(
        quote_ident(st.schemaname)||'.'||quote_ident(st.relname)
    ) / 1048576.0, 2)                                           AS size_mb
FROM pg_stat_user_tables st
${schema ? `WHERE st.schemaname = '${schema}'` : ''}
ORDER BY total_accesses DESC
LIMIT 25;`,
  },

  // ── Most Queried Columns ───────────────────────────────────────────────────
  most_queried_columns: {

    snowflake: ({ table = '', days = 30 }) => `\
-- Column access frequency for table '${table.toUpperCase()}' — last ${days} days
-- Requires ACCOUNT_USAGE.ACCESS_HISTORY (Enterprise tier)
-- Two-level flatten: first into each table entry, then into its columns array
SELECT
    col.value:columnName::STRING    AS column_name,
    COUNT(*)                        AS access_count,
    MAX(h.query_start_time)::DATE   AS last_accessed
FROM snowflake.account_usage.access_history h,
     LATERAL FLATTEN(input => columns_accessed)       tbl,
     LATERAL FLATTEN(input => tbl.value:columns)      col
WHERE tbl.value:objectName = '${table.toUpperCase()}'
  AND h.query_start_time >= DATEADD('day', -${days}, CURRENT_TIMESTAMP())
GROUP BY 1
ORDER BY 2 DESC;`,

    databricks: ({ schema = 'default', table = '' }) => `\
-- Column info and data types for '${schema || 'default'}.${table}'
SELECT
    column_name,
    data_type,
    is_nullable,
    ordinal_position
FROM system.information_schema.columns
WHERE table_name   = '${table}'
  AND table_schema = '${schema || 'default'}'
ORDER BY ordinal_position;`,

    azure_sql: ({ schema = 'dbo', table = '' }) => `\
-- Column info and statistics for [${schema || 'dbo'}].[${table}]
SELECT
    c.COLUMN_NAME,
    c.DATA_TYPE,
    c.CHARACTER_MAXIMUM_LENGTH  AS max_chars,
    c.NUMERIC_PRECISION,
    c.NUMERIC_SCALE,
    c.IS_NULLABLE,
    c.ORDINAL_POSITION
FROM INFORMATION_SCHEMA.COLUMNS c
WHERE c.TABLE_NAME   = '${table}'
  AND c.TABLE_SCHEMA = '${schema || 'dbo'}'
ORDER BY c.ORDINAL_POSITION;`,

    sqlserver: ({ schema = 'dbo', table = '' }) => `\
-- Column info for [${schema || 'dbo'}].[${table}]
SELECT
    c.COLUMN_NAME,
    c.DATA_TYPE,
    c.CHARACTER_MAXIMUM_LENGTH  AS max_chars,
    c.NUMERIC_PRECISION,
    c.IS_NULLABLE,
    c.ORDINAL_POSITION
FROM INFORMATION_SCHEMA.COLUMNS c
WHERE c.TABLE_NAME   = '${table}'
  AND c.TABLE_SCHEMA = '${schema || 'dbo'}'
ORDER BY c.ORDINAL_POSITION;`,

    postgres: ({ schema = 'public', table = '' }) => `\
-- Column stats for '${schema || 'public'}.${table}'
-- n_distinct < 0 means "fraction of rows", e.g. -0.5 = ~50% unique
SELECT
    c.attname                                               AS column_name,
    pg_catalog.format_type(c.atttypid, c.atttypmod)        AS data_type,
    c.attnotnull                                            AS not_null,
    s.n_distinct,
    ROUND((s.null_frac * 100)::numeric, 2)                 AS null_pct,
    s.avg_width                                             AS avg_bytes,
    s.correlation                                           AS sort_correlation
FROM pg_attribute c
JOIN pg_class t  ON c.attrelid = t.oid
JOIN pg_namespace ns ON t.relnamespace = ns.oid
LEFT JOIN pg_stats s
    ON s.schemaname = ns.nspname
   AND s.tablename  = t.relname
   AND s.attname    = c.attname
WHERE t.relname  = '${table}'
  AND ns.nspname = '${schema || 'public'}'
  AND c.attnum > 0
  AND NOT c.attisdropped
ORDER BY c.attnum;`,
  },

  // ── Most Expensive Queries ─────────────────────────────────────────────────
  most_expensive_queries: {

    snowflake: ({ schema = '', days = 7 }) => `\
-- Most expensive queries${schema ? ` in schema '${schema}'` : ''} — last ${days} days
SELECT
    query_id,
    LEFT(query_text, 300)                               AS query_preview,
    database_name,
    schema_name,
    ROUND(total_elapsed_time / 1000.0, 2)              AS total_seconds,
    ROUND(execution_time / 1000.0, 2)                  AS exec_seconds,
    ROUND(bytes_scanned / 1073741824.0, 3)             AS gb_scanned,
    rows_produced,
    partitions_scanned,
    partitions_total,
    ROUND(partitions_scanned * 100.0
          / NULLIF(partitions_total, 0), 1)            AS pct_partitions_scanned
FROM snowflake.account_usage.query_history
WHERE start_time >= DATEADD('day', -${days}, CURRENT_TIMESTAMP())
  AND execution_status = 'SUCCESS'
  ${schema ? `AND schema_name = '${schema.toUpperCase()}'` : ''}
ORDER BY total_elapsed_time DESC
LIMIT 25;`,

    databricks: ({ days = 7 }) => `\
-- Most expensive queries — last ${days} days (Unity Catalog)
SELECT
    statement_id,
    LEFT(statement_text, 300)               AS query_preview,
    statement_type,
    ROUND(total_duration_ms / 1000.0, 2)    AS total_seconds,
    ROUND(read_bytes / 1048576.0, 2)        AS mb_read,
    read_rows,
    produced_rows,
    status,
    error_message
FROM system.query.history
WHERE created_at >= CURRENT_TIMESTAMP() - INTERVAL ${days} DAYS
  AND total_duration_ms IS NOT NULL
ORDER BY total_duration_ms DESC
LIMIT 25;`,

    azure_sql: () => `\
-- Top 25 most expensive queries (plan cache — resets on restart)
SELECT TOP 25
    qs.execution_count,
    ROUND(qs.total_elapsed_time / 1000.0, 2)                    AS total_ms,
    ROUND(qs.total_elapsed_time / qs.execution_count / 1000.0, 2) AS avg_ms,
    qs.total_logical_reads / qs.execution_count                 AS avg_logical_reads,
    ROUND(qs.total_worker_time / qs.execution_count / 1000.0, 2) AS avg_cpu_ms,
    LEFT(qt.text, 300)                                           AS query_preview,
    DB_NAME(qt.dbid)                                             AS database_name
FROM sys.dm_exec_query_stats qs
CROSS APPLY sys.dm_exec_sql_text(qs.sql_handle) qt
ORDER BY qs.total_elapsed_time DESC;`,

    sqlserver: () => `\
-- Top 25 most expensive queries (plan cache — resets on restart)
SELECT TOP 25
    qs.execution_count,
    ROUND(qs.total_elapsed_time / 1000.0, 2)                    AS total_ms,
    ROUND(qs.total_elapsed_time / qs.execution_count / 1000.0, 2) AS avg_ms,
    qs.total_logical_reads / qs.execution_count                 AS avg_logical_reads,
    ROUND(qs.total_worker_time / qs.execution_count / 1000.0, 2) AS avg_cpu_ms,
    LEFT(qt.text, 300)                                           AS query_preview,
    DB_NAME(qt.dbid)                                             AS database_name
FROM sys.dm_exec_query_stats qs
CROSS APPLY sys.dm_exec_sql_text(qs.sql_handle) qt
ORDER BY qs.total_elapsed_time DESC;`,

    postgres: () => `\
-- Most expensive queries (requires pg_stat_statements extension)
-- Enable with: CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
SELECT
    LEFT(query, 300)                                    AS query_preview,
    calls,
    ROUND(total_exec_time::numeric / 1000, 2)          AS total_seconds,
    ROUND(mean_exec_time::numeric / 1000, 4)           AS avg_seconds,
    ROUND(stddev_exec_time::numeric / 1000, 4)         AS stddev_seconds,
    rows,
    shared_blks_hit,
    shared_blks_read,
    ROUND(100.0 * shared_blks_hit
          / NULLIF(shared_blks_hit + shared_blks_read, 0), 1) AS cache_hit_pct
FROM pg_stat_statements
ORDER BY total_exec_time DESC
LIMIT 25;`,
  },
}

/**
 * Returns the SQL string for a given insight type and warehouse.
 * @param {string} queryType  - key from INSIGHT_TYPES
 * @param {string} warehouseKey - key from WAREHOUSES in App.jsx
 * @param {object} params     - user-provided params (schema, table, days, …)
 */
export function getInsightSql(queryType, warehouseKey, params = {}) {
  const fn = SQL[queryType]?.[warehouseKey]
  if (!fn) return `-- No pre-built query available for warehouse "${warehouseKey}" + insight "${queryType}"`
  return fn(params)
}
