import psycopg2
import psycopg2.extras
import config
import queries
from storage import Recommendation


def _connect():
    return psycopg2.connect(
        host=config.DB_HOST,
        port=config.DB_PORT,
        dbname=config.DB_NAME,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        connect_timeout=10,
    )


def _fetch(conn, sql: str, params: dict = None) -> list[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params or {})
        return cur.fetchall()


# ── Index analysis ────────────────────────────────────────────────────────────

def analyze_indexes(conn) -> list[Recommendation]:
    recs = []

    # Missing indexes
    rows = _fetch(conn, queries.MISSING_INDEXES, {
        "min_rows": config.MIN_TABLE_ROWS,
        "min_seq_scans": config.MIN_SEQ_SCANS,
    })
    for r in rows:
        pct = float(r["seq_scan_pct"] or 0)
        if pct >= config.SEQ_SCAN_PCT_WARN * 100:
            severity = "critical" if pct >= 90 else "warning"
            recs.append(Recommendation(
                category="index",
                severity=severity,
                title=f"Missing index on table '{r['table_name']}'",
                description=(
                    f"{pct}% of accesses to '{r['table_name']}' are sequential scans "
                    f"({r['seq_scan']} seq vs {r['idx_scan']} idx) on {r['n_live_tup']:,} rows."
                ),
                action=(
                    "Run EXPLAIN ANALYZE on the most frequent queries touching this table. "
                    "Identify the most selective WHERE columns and create a B-tree index."
                ),
                sql=(
                    f"-- Find heavy queries on this table:\n"
                    f"SELECT LEFT(query,200), calls, mean_exec_time\n"
                    f"FROM pg_stat_statements\n"
                    f"WHERE query ILIKE '%{r['table_name']}%'\n"
                    f"ORDER BY mean_exec_time DESC LIMIT 5;"
                ),
            ))

    # Unused indexes
    rows = _fetch(conn, queries.UNUSED_INDEXES)
    for r in rows:
        size_mb = r["index_size_bytes"] / 1024 / 1024
        if size_mb < 1:
            severity = "info"
        elif size_mb < 50:
            severity = "warning"
        else:
            severity = "critical"
        recs.append(Recommendation(
            category="index",
            severity=severity,
            title=f"Unused index '{r['indexname']}'",
            description=(
                f"Index '{r['indexname']}' on '{r['tablename']}' "
                f"has never been used (idx_scan=0) and occupies {r['index_size']}."
            ),
            action=(
                "Verify the index is not needed for constraints or rare queries. "
                "If confirmed unused, drop it to speed up writes and save space."
            ),
            sql=f"DROP INDEX CONCURRENTLY {r['schemaname']}.{r['indexname']};",
        ))

    return recs


# ── Workload analysis ─────────────────────────────────────────────────────────

def analyze_workload(conn) -> list[Recommendation]:
    recs = []

    # Slow queries
    rows = _fetch(conn, queries.SLOW_QUERIES)
    for r in rows:
        mean_ms = float(r["mean_ms"] or 0)
        if mean_ms < config.SLOW_QUERY_WARN_MS:
            continue
        severity = "critical" if mean_ms >= config.SLOW_QUERY_CRIT_MS else "warning"
        recs.append(Recommendation(
            category="workload",
            severity=severity,
            title=f"Slow query (avg {mean_ms} ms) — queryid {r['queryid']}",
            description=(
                f"Query called {r['calls']} times, avg {mean_ms} ms, "
                f"takes {r['pct_total_time']}% of total DB time. "
                f"Preview: {r['query_preview']}"
            ),
            action=(
                "Run EXPLAIN (ANALYZE, BUFFERS) to inspect the execution plan. "
                "Look for Seq Scan on large tables — consider adding an index."
            ),
            sql=f"EXPLAIN (ANALYZE, BUFFERS)\n{r['query_preview']};",
        ))

    # Long-running transactions
    rows = _fetch(conn, queries.LONG_TRANSACTIONS, {
        "warn_sec": config.LONG_TX_WARN_SEC,
    })
    for r in rows:
        dur = int(r["tx_duration_sec"])
        severity = "critical" if dur >= config.LONG_TX_CRIT_SEC else "warning"
        recs.append(Recommendation(
            category="workload",
            severity=severity,
            title=f"Long transaction — pid {r['pid']} ({dur}s)",
            description=(
                f"Transaction open for {dur}s by user '{r['usename']}' "
                f"from {r['client_addr']}, state: {r['state']}. "
                f"Query: {r['query_preview']}"
            ),
            action=(
                "Investigate whether the transaction is stuck or intentional. "
                "Long idle-in-transaction holds locks and bloats tables."
            ),
            sql=(
                f"-- Cancel query (soft):\nSELECT pg_cancel_backend({r['pid']});\n"
                f"-- Terminate connection (hard):\nSELECT pg_terminate_backend({r['pid']});"
            ),
        ))

    return recs


# ── Health analysis ───────────────────────────────────────────────────────────

def analyze_health(conn) -> list[Recommendation]:
    recs = []

    # Cache hit ratio
    rows = _fetch(conn, queries.CACHE_HIT_RATIO)
    for r in rows:
        ratio = float(r["ratio"] or 1)
        if ratio < config.CACHE_HIT_RATIO_CRIT:
            severity = "critical"
        elif ratio < config.CACHE_HIT_RATIO_WARN:
            severity = "warning"
        else:
            continue
        pct = round(ratio * 100, 1)
        recs.append(Recommendation(
            category="health",
            severity=severity,
            title=f"Low cache hit ratio on '{r['datname']}' ({pct}%)",
            description=(
                f"Cache hit ratio is {pct}% (threshold: {config.CACHE_HIT_RATIO_WARN*100}%). "
                f"PostgreSQL is reading from disk too often."
            ),
            action="Increase shared_buffers (currently set in postgresql.conf). "
                   "Recommended: 25% of total RAM. Requires restart.",
            sql="SHOW shared_buffers;",
        ))

    # Dead tuples / autovacuum lag
    rows = _fetch(conn, queries.DEAD_TUPLES)
    for r in rows:
        ratio = float(r["dead_ratio"] or 0)
        if ratio < config.DEAD_RATIO_WARN:
            continue
        severity = "critical" if ratio >= config.DEAD_RATIO_CRIT else "warning"
        pct = round(ratio * 100, 1)
        recs.append(Recommendation(
            category="health",
            severity=severity,
            title=f"High dead tuple ratio on '{r['table_name']}' ({pct}%)",
            description=(
                f"Table '{r['table_name']}' has {r['n_dead_tup']:,} dead tuples "
                f"({pct}% of total). Last autovacuum: {r['last_autovacuum']}."
            ),
            action=(
                "Run VACUUM ANALYZE manually. If this recurs, consider tuning "
                "autovacuum_vacuum_scale_factor for this table."
            ),
            sql=f"VACUUM ANALYZE {r['table_name']};",
        ))

    return recs


# ── Config analysis ───────────────────────────────────────────────────────────

def _to_mb(setting: str, unit: str) -> float:
    """Convert pg_settings value to MB."""
    val = float(setting)
    if unit == "8kB":
        return val * 8 / 1024
    if unit == "kB":
        return val / 1024
    if unit == "MB":
        return val
    if unit == "GB":
        return val * 1024
    return val


def analyze_config(conn) -> list[Recommendation]:
    recs = []
    rows = _fetch(conn, queries.CONFIG_PARAMS)
    params = {r["name"]: r for r in rows}
    ram = config.TOTAL_RAM_MB

    def get_mb(name):
        r = params.get(name)
        if r is None:
            return None
        return _to_mb(r["setting"], r["unit"] or "")

    # shared_buffers should be ~25% RAM
    sb = get_mb("shared_buffers")
    if sb is not None:
        recommended = ram * 0.25
        if sb < ram * 0.20:
            recs.append(Recommendation(
                category="config",
                severity="warning",
                title="shared_buffers is below recommended value",
                description=(
                    f"shared_buffers = {sb:.0f} MB, recommended ~{recommended:.0f} MB "
                    f"(25% of {ram} MB RAM)."
                ),
                action="Increase shared_buffers in postgresql.conf and restart PostgreSQL.",
                sql=f"-- In postgresql.conf:\nshared_buffers = '{int(recommended)}MB'",
            ))

    # work_mem — warn if very low and slow queries exist
    wm = get_mb("work_mem")
    if wm is not None and wm < 4:
        recs.append(Recommendation(
            category="config",
            severity="info",
            title="work_mem is very low (< 4 MB)",
            description=(
                f"work_mem = {wm:.0f} MB. Sort and hash operations may spill to disk."
            ),
            action=(
                "Increase work_mem carefully — it applies per sort/hash operation, "
                "and multiple operations can run per connection."
            ),
            sql="-- In postgresql.conf:\nwork_mem = '16MB'",
        ))

    # max_connections > 200 without pooler
    mc = params.get("max_connections")
    if mc and int(mc["setting"]) > 200:
        recs.append(Recommendation(
            category="config",
            severity="info",
            title=f"max_connections is high ({mc['setting']})",
            description=(
                f"max_connections = {mc['setting']}. "
                "Each idle connection consumes ~5-10 MB RAM."
            ),
            action="Consider using PgBouncer connection pooler to reduce connection overhead.",
            sql=None,
        ))

    # checkpoint_completion_target should be >= 0.7
    cct = params.get("checkpoint_completion_target")
    if cct and float(cct["setting"]) < 0.7:
        recs.append(Recommendation(
            category="config",
            severity="info",
            title="checkpoint_completion_target is low",
            description=(
                f"checkpoint_completion_target = {cct['setting']}. "
                "This can cause IO spikes during checkpoints."
            ),
            action="Set checkpoint_completion_target = 0.9 in postgresql.conf.",
            sql="-- In postgresql.conf:\ncheckpoint_completion_target = 0.9",
        ))

    # pg_stat_statements fill level
    fill_rows = _fetch(conn, queries.PG_STAT_STATEMENTS_FILL)
    if fill_rows:
        f = fill_rows[0]
        current = int(f["current_count"])
        maximum = int(f["max_count"] or 5000)
        if maximum > 0 and current / maximum >= config.PG_STAT_STATEMENTS_MAX_WARN:
            pct = round(current / maximum * 100, 1)
            recs.append(Recommendation(
                category="config",
                severity="warning",
                title=f"pg_stat_statements is {pct}% full",
                description=(
                    f"{current}/{maximum} query slots used. "
                    "When full, new queries evict old ones — statistics become incomplete."
                ),
                action=(
                    "Reset statistics if data is stale, or increase "
                    "pg_stat_statements.max in postgresql.conf."
                ),
                sql="SELECT pg_stat_statements_reset();",
            ))

    return recs


# ── Entry point ───────────────────────────────────────────────────────────────

def run_analysis() -> list[Recommendation]:
    try:
        conn = _connect()
        results = (
            analyze_indexes(conn)
            + analyze_workload(conn)
            + analyze_health(conn)
            + analyze_config(conn)
        )
        conn.close()
        return results
    except Exception as e:
        print(f"[analyzer] ERROR during analysis: {e}")
        return []
