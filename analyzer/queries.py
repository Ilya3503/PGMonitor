"""
All SQL queries used by the analyzer.
Plain string constants — no logic, no f-strings, no business rules.

IMPORTANT: in psycopg2, '%' inside SQL is treated as a parameter
placeholder. All literal '%' (modulo operators, LIKE wildcards) must
be written as '%%' so they survive parameter substitution.

The bloat queries are adapted from pgexperts/pgx_scripts
(table_bloat_check.sql, index_bloat_check.sql).
"""

PG_STAT_STATEMENTS_AVAILABLE = """
SELECT EXISTS (
    SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements'
) AS available;
"""

# ─────────────────────────────────────────────────────────────────────────────
# 1. INDEXES
# ─────────────────────────────────────────────────────────────────────────────

MISSING_INDEXES = """
SELECT
    schemaname,
    relname                                                    AS table_name,
    seq_scan,
    COALESCE(idx_scan, 0)                                      AS idx_scan,
    n_live_tup,
    seq_tup_read,
    ROUND(
        seq_scan::numeric / NULLIF(seq_scan + idx_scan, 0) * 100, 1
    )                                                          AS seq_scan_pct,
    pg_size_pretty(pg_relation_size(relid))                    AS table_size
FROM pg_stat_user_tables
WHERE n_live_tup   > %(min_rows)s
  AND seq_scan     > %(min_seq_scans)s
  AND seq_scan     > COALESCE(idx_scan, 0)
  AND seq_tup_read > n_live_tup * 5
ORDER BY seq_tup_read DESC
LIMIT 20;
"""

QUERIES_BY_TABLE = """
SELECT
    queryid::text                              AS queryid,
    LEFT(query, 300)                           AS query_preview,
    calls,
    ROUND(mean_exec_time::numeric, 2)          AS mean_ms
FROM pg_stat_statements
WHERE query ILIKE %(pattern)s
  AND query NOT ILIKE '%%pg_stat%%'
ORDER BY total_exec_time DESC
LIMIT 5;
"""

UNUSED_INDEXES = """
SELECT
    s.schemaname,
    s.relname                                       AS tablename,
    s.indexrelname                                  AS indexname,
    s.idx_scan,
    pg_size_pretty(pg_relation_size(s.indexrelid))  AS index_size,
    pg_relation_size(s.indexrelid)                  AS index_size_bytes
FROM pg_stat_user_indexes s
JOIN pg_index i ON i.indexrelid = s.indexrelid
WHERE s.idx_scan = 0
  AND NOT i.indisprimary
  AND NOT i.indisunique
  AND pg_relation_size(s.indexrelid) > %(min_bytes)s
ORDER BY pg_relation_size(s.indexrelid) DESC
LIMIT 20;
"""

INDEX_BLOAT = """
WITH btree_index_atts AS (
    SELECT
        nspname, indexclass.relname AS index_name,
        indexclass.reltuples, indexclass.relpages, indrelid, indexrelid,
        indexclass.relam, tableclass.relname AS tablename,
        regexp_split_to_table(indkey::text, ' ')::smallint AS attnum,
        indexrelid AS index_oid
    FROM pg_index
    JOIN pg_class indexclass ON pg_index.indexrelid = indexclass.oid
    JOIN pg_class tableclass ON pg_index.indrelid = tableclass.oid
    JOIN pg_namespace ON pg_namespace.oid = indexclass.relnamespace
    JOIN pg_am ON indexclass.relam = pg_am.oid
    WHERE pg_am.amname = 'btree'
      AND indexclass.relpages > 0
      AND nspname NOT IN ('pg_catalog', 'information_schema')
),
index_item_sizes AS (
    SELECT
        ind_atts.nspname, ind_atts.index_name,
        ind_atts.reltuples, ind_atts.relpages, ind_atts.relam,
        indrelid AS table_oid, index_oid,
        current_setting('block_size')::numeric AS bs,
        8 AS maxalign, 24 AS pagehdr,
        CASE WHEN max(coalesce(pg_stats.null_frac,0)) = 0 THEN 2 ELSE 6 END AS index_tuple_hdr,
        sum( (1 - coalesce(pg_stats.null_frac, 0))
             * coalesce(pg_stats.avg_width, 1024) ) AS nulldatawidth
    FROM pg_attribute
    JOIN btree_index_atts AS ind_atts
      ON pg_attribute.attrelid = ind_atts.indexrelid
     AND pg_attribute.attnum = ind_atts.attnum
    JOIN pg_stats ON pg_stats.schemaname = ind_atts.nspname
                 AND ((pg_stats.tablename = ind_atts.tablename
                       AND pg_stats.attname = pg_get_indexdef(pg_attribute.attrelid, pg_attribute.attnum, TRUE))
                  OR  (pg_stats.tablename = ind_atts.index_name
                       AND pg_stats.attname = pg_attribute.attname))
    WHERE pg_attribute.attnum > 0
    GROUP BY 1,2,3,4,5,6,7,8,9
),
index_aligned_est AS (
    SELECT maxalign, bs, nspname, index_name, reltuples, relpages, relam,
        table_oid, index_oid, ( 2 +
            maxalign - CASE
                WHEN index_tuple_hdr%%maxalign = 0 THEN maxalign
                ELSE index_tuple_hdr%%maxalign END
          + nulldatawidth + maxalign - CASE
                WHEN nulldatawidth::integer%%maxalign = 0 THEN maxalign
                ELSE nulldatawidth::integer%%maxalign END
        )::numeric AS nulldatahdrwidth, pagehdr
    FROM index_item_sizes
),
raw_bloat AS (
    SELECT
        current_database() AS dbname, nspname, table_oid::regclass AS table_name,
        index_oid::regclass AS index_name,
        bs*(relpages)::bigint AS totalbytes,
        CEIL((reltuples*(4+nulldatahdrwidth)) / (bs-pagehdr::float)) AS expectedpages,
        bs*(relpages-CEIL((reltuples*(4+nulldatahdrwidth))/(bs-pagehdr::float)))::bigint AS wastedbytes
    FROM index_aligned_est
)
SELECT
    nspname                                       AS schemaname,
    table_name::text                              AS tablename,
    index_name::text                              AS indexname,
    pg_size_pretty(totalbytes)                    AS index_size,
    pg_size_pretty(GREATEST(wastedbytes, 0))      AS wasted_size,
    ROUND(
        (100.0 * GREATEST(wastedbytes, 0) / NULLIF(totalbytes, 0))::numeric, 1
    )                                             AS bloat_pct,
    totalbytes                                    AS total_bytes,
    GREATEST(wastedbytes, 0)                      AS wasted_bytes
FROM raw_bloat
WHERE totalbytes > %(min_bytes)s
  AND wastedbytes > 0
  AND (100.0 * wastedbytes / NULLIF(totalbytes, 0)) >= %(min_pct)s
ORDER BY wastedbytes DESC
LIMIT 20;
"""

# ─────────────────────────────────────────────────────────────────────────────
# 2. BLOAT
# ─────────────────────────────────────────────────────────────────────────────

TABLE_BLOAT = """
WITH constants AS (
    SELECT current_setting('block_size')::numeric AS bs, 23 AS hdr, 8 AS ma
),
no_stats AS (
    SELECT table_schema, table_name,
           n_live_tup::numeric AS est_rows,
           pg_table_size(relid)::numeric AS table_size
    FROM information_schema.columns
    JOIN pg_stat_user_tables AS psut
      ON table_schema = psut.schemaname AND table_name = psut.relname
    LEFT OUTER JOIN pg_stats
      ON table_schema = pg_stats.schemaname
     AND table_name   = pg_stats.tablename
     AND column_name  = attname
    WHERE attname IS NULL
      AND table_schema NOT IN ('pg_catalog', 'information_schema')
    GROUP BY table_schema, table_name, relid, n_live_tup
),
null_headers AS (
    SELECT
        hdr + 1
            + (sum(case when null_frac <> 0 then 1 else 0 end) / 8) AS nullhdr,
        SUM((1-null_frac)*avg_width) AS datawidth,
        MAX(null_frac) AS maxfracsum,
        schemaname, tablename, hdr, ma, bs
    FROM pg_stats CROSS JOIN constants
    LEFT OUTER JOIN no_stats
      ON schemaname = no_stats.table_schema AND tablename = no_stats.table_name
    WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
      AND no_stats.table_name IS NULL
      AND EXISTS (SELECT 1 FROM information_schema.columns
                  WHERE schemaname = columns.table_schema
                    AND tablename  = columns.table_name)
    GROUP BY schemaname, tablename, hdr, ma, bs
),
data_headers AS (
    SELECT
        ma, bs, hdr, schemaname, tablename,
        (datawidth + (hdr+ma-(case when hdr%%ma=0 THEN ma ELSE hdr%%ma END)))::numeric AS datahdr,
        (maxfracsum*(nullhdr+ma-(case when nullhdr%%ma=0 THEN ma ELSE nullhdr%%ma END))) AS nullhdr2
    FROM null_headers
),
table_estimates AS (
    SELECT schemaname, tablename, bs,
           reltuples::numeric AS est_rows, relpages * bs AS table_bytes,
           CEIL((reltuples * (datahdr + nullhdr2 + 4 + ma -
                (CASE WHEN datahdr%%ma=0 THEN ma ELSE datahdr%%ma END)) / (bs - 20::float))) * bs AS expected_bytes
    FROM data_headers
    JOIN pg_class ON tablename = relname
    JOIN pg_namespace ON relnamespace = pg_namespace.oid AND schemaname = nspname
    WHERE pg_class.relkind = 'r'
)
SELECT
    schemaname,
    tablename,
    pg_size_pretty(table_bytes::bigint)                          AS table_size,
    pg_size_pretty((table_bytes - expected_bytes)::bigint)       AS bloat_size,
    ROUND(
        (100.0 * (table_bytes - expected_bytes)
            / NULLIF(table_bytes, 0))::numeric, 1
    )                                                            AS bloat_pct,
    table_bytes,
    (table_bytes - expected_bytes)                               AS wasted_bytes
FROM table_estimates
WHERE table_bytes > %(min_bytes)s
  AND expected_bytes > 0
  AND table_bytes > expected_bytes
  AND (100.0 * (table_bytes - expected_bytes) / NULLIF(table_bytes, 0)) >= %(min_pct)s
ORDER BY (table_bytes - expected_bytes) DESC
LIMIT 20;
"""

# ─────────────────────────────────────────────────────────────────────────────
# 3. QUERIES
# ─────────────────────────────────────────────────────────────────────────────

HEAVY_QUERIES = """
SELECT
    queryid::text                                            AS queryid,
    LEFT(query, 400)                                         AS query_preview,
    calls,
    ROUND(mean_exec_time::numeric, 2)                        AS mean_ms,
    ROUND(total_exec_time::numeric / 1000, 2)                AS total_sec,
    ROUND(
        (100.0 * total_exec_time
            / NULLIF(SUM(total_exec_time) OVER (), 0))::numeric, 2
    )                                                        AS pct_total_time,
    rows / NULLIF(calls, 0)                                  AS avg_rows
FROM pg_stat_statements
WHERE query NOT ILIKE '%%pg_stat%%'
  AND query NOT ILIKE '%%pg_advisor%%'
  AND query NOT ILIKE '%%pg_settings%%'
  AND query NOT ILIKE 'BEGIN%%'
  AND query NOT ILIKE 'COMMIT%%'
ORDER BY total_exec_time DESC
LIMIT 10;
"""

# ─────────────────────────────────────────────────────────────────────────────
# 4. CONFIG
# ─────────────────────────────────────────────────────────────────────────────

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
    'shared_preload_libraries',
    'log_min_duration_statement',
    'pg_stat_statements.max'
);
"""

PG_STAT_STATEMENTS_FILL = """
SELECT
    COUNT(*)                                       AS current_count,
    (SELECT setting::int FROM pg_settings
     WHERE name = 'pg_stat_statements.max')        AS max_count
FROM pg_stat_statements;
"""