# All SQL queries used by the analyzer.
# No logic here — just constants.

# ── Indexes ──────────────────────────────────────────────────────────────────

MISSING_INDEXES = """
SELECT
    relname                                                         AS table_name,
    seq_scan,
    idx_scan,
    n_live_tup,
    ROUND(
        seq_scan::numeric / NULLIF(seq_scan + idx_scan, 0) * 100, 1
    )                                                               AS seq_scan_pct
FROM pg_stat_user_tables
WHERE n_live_tup   > %(min_rows)s
  AND seq_scan     > %(min_seq_scans)s
  AND seq_scan > COALESCE(idx_scan, 0)
  AND seq_tup_read > n_live_tup * 5
ORDER BY seq_tup_read DESC
LIMIT 20;
"""

UNUSED_INDEXES = """
SELECT
    s.schemaname,
    s.relname AS tablename,
    s.indexrelname AS indexname,
    s.idx_scan,
    pg_size_pretty(pg_relation_size(s.indexrelid)) AS index_size,
    pg_relation_size(s.indexrelid)                 AS index_size_bytes
FROM pg_stat_user_indexes s
JOIN pg_index i ON i.indexrelid = s.indexrelid
WHERE s.idx_scan = 0
  AND NOT i.indisprimary
  AND NOT i.indisunique
ORDER BY pg_relation_size(s.indexrelid) DESC
LIMIT 20;
"""

# ── Workload ──────────────────────────────────────────────────────────────────

SLOW_QUERIES = """
SELECT
    queryid::text                               AS queryid,
    LEFT(query, 200)                            AS query_preview,
    calls,
    ROUND(mean_exec_time::numeric, 2)           AS mean_ms,
    ROUND(total_exec_time::numeric / 1000, 2)   AS total_sec,
    ROUND(
        (
            100.0 * total_exec_time
            / NULLIF(SUM(total_exec_time) OVER (), 0)
        )::numeric, 2
    )                                           AS pct_total_time,
    rows / NULLIF(calls, 0)                    AS avg_rows
FROM pg_stat_statements
WHERE query NOT LIKE '%%pg_stat%%'
  AND query NOT LIKE '%%pg_advisor%%'
ORDER BY mean_exec_time DESC
LIMIT 15;
"""

LONG_TRANSACTIONS = """
SELECT
    pid,
    usename,
    client_addr::text,
    state,
    ROUND(EXTRACT(EPOCH FROM (now() - xact_start))::numeric, 0) AS tx_duration_sec,
    LEFT(query, 200)                                             AS query_preview
FROM pg_stat_activity
WHERE xact_start IS NOT NULL
  AND state IN ('active', 'idle in transaction')
  AND EXTRACT(EPOCH FROM (now() - xact_start)) > %(warn_sec)s
ORDER BY tx_duration_sec DESC;
"""

# ── Health ────────────────────────────────────────────────────────────────────

CACHE_HIT_RATIO = """
SELECT
    datname,
    ROUND(
        blks_hit::numeric / NULLIF(blks_hit + blks_read, 0), 4
    ) AS ratio
FROM pg_stat_database
WHERE datname NOT IN ('template0', 'template1', 'postgres')
  AND (blks_hit + blks_read) > 0;
"""

DEAD_TUPLES = """
SELECT
    relname                                     AS table_name,
    n_dead_tup,
    n_live_tup,
    ROUND(
        n_dead_tup::numeric
            / NULLIF(n_live_tup + n_dead_tup, 0), 4
    )                                           AS dead_ratio,
    last_autovacuum,
    last_autoanalyze
FROM pg_stat_user_tables
WHERE n_live_tup > 1000
  AND n_dead_tup > 500
ORDER BY dead_ratio DESC
LIMIT 15;
"""

# ── Config ────────────────────────────────────────────────────────────────────

CONFIG_PARAMS = """
SELECT name, setting, unit
FROM pg_settings
WHERE name IN (
    'shared_buffers',
    'work_mem',
    'maintenance_work_mem',
    'effective_cache_size',
    'max_connections',
    'checkpoint_completion_target',
    'wal_buffers',
    'max_wal_size',
    'autovacuum',
    'autovacuum_vacuum_scale_factor',
    'autovacuum_analyze_scale_factor',
    'shared_preload_libraries',
    'log_min_duration_statement',
    'pg_stat_statements.max'
);
"""

PG_STAT_STATEMENTS_FILL = """
SELECT
    COUNT(*)                                        AS current_count,
    (SELECT setting::int FROM pg_settings
     WHERE name = 'pg_stat_statements.max')        AS max_count
FROM pg_stat_statements;
"""