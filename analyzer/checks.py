from dataclasses import dataclass, asdict
from typing import Optional
import psycopg2.extras

import config
import queries


@dataclass
class Recommendation:
    category: str          # index | bloat | query | config
    severity: str          # critical | warning | info
    title: str             # short headline
    description: str       # what the data shows
    action: str            # what to do
    sql: Optional[str]     # ready-to-copy SQL

    def to_dict(self) -> dict:
        return asdict(self)


def _fetch(conn, sql: str, params: dict | None = None) -> list[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params or {})
        return cur.fetchall()


def _pg_stat_statements_available(conn) -> bool:
    rows = _fetch(conn, queries.PG_STAT_STATEMENTS_AVAILABLE)
    return bool(rows and rows[0].get("available"))


# ─────────────────────────────────────────────────────────────────────────────
# Block 1: INDEXES
# ─────────────────────────────────────────────────────────────────────────────

def check_indexes(conn) -> list[Recommendation]:
    recs: list[Recommendation] = []
    has_pgss = _pg_stat_statements_available(conn)

    # 1.1 Missing indexes
    rows = _fetch(conn, queries.MISSING_INDEXES, {
        "min_rows": config.MIN_TABLE_ROWS,
        "min_seq_scans": config.MIN_SEQ_SCANS,
    })
    for r in rows:
        pct = float(r["seq_scan_pct"] or 0)
        if pct < config.SEQ_SCAN_PCT_WARN:
            continue

        severity = "critical" if pct >= 90 else "warning"
        table = r["table_name"]

        # Enrich with sample queries hitting this table — only if pgss is available
        sample_queries = ""
        if has_pgss:
            samples = _fetch(conn, queries.QUERIES_BY_TABLE, {
                "pattern": f"%{table}%"
            })
            if samples:
                lines = [f"-- Top queries on '{table}' (review WHERE clauses):"]
                for s in samples:
                    lines.append(
                        f"-- [{s['calls']} calls, {s['mean_ms']} ms avg]\n"
                        f"-- {s['query_preview']}\n"
                    )
                sample_queries = "\n".join(lines) + "\n"

        recs.append(Recommendation(
            category="index",
            severity=severity,
            title=f"Missing index on '{table}'",
            description=(
                f"Table '{table}' ({r['table_size']}, {r['n_live_tup']:,} rows) "
                f"is read mostly via sequential scans: "
                f"{r['seq_scan']:,} seq vs {r['idx_scan']:,} idx ({pct}%)."
            ),
            action=(
                "Identify the most frequent WHERE columns from the queries below "
                "and create a B-tree index on them."
            ),
            sql=(
                f"{sample_queries}"
                f"-- Once you know the column(s):\n"
                f"-- CREATE INDEX CONCURRENTLY idx_{table}_<col> ON {table} (<col>);"
            ),
        ))

    # 1.2 Unused indexes
    rows = _fetch(conn, queries.UNUSED_INDEXES, {
        "min_bytes": int(config.UNUSED_INDEX_MIN_MB * 1024 * 1024),
    })
    for r in rows:
        size_mb = r["index_size_bytes"] / 1024 / 1024
        severity = "critical" if size_mb >= 100 else "warning" if size_mb >= 10 else "info"
        recs.append(Recommendation(
            category="index",
            severity=severity,
            title=f"Unused index '{r['indexname']}'",
            description=(
                f"Index '{r['indexname']}' on '{r['tablename']}' "
                f"has never been used since stats reset (idx_scan = 0). "
                f"Occupies {r['index_size']}."
            ),
            action=(
                "Verify the index is truly unused in your workload "
                "(check different time periods). If confirmed, drop it "
                "to speed up writes and free space."
            ),
            sql=f"DROP INDEX CONCURRENTLY {r['schemaname']}.{r['indexname']};",
        ))

    # 1.3 Bloated indexes
    rows = _fetch(conn, queries.INDEX_BLOAT, {
        "min_bytes": int(config.BLOAT_MIN_SIZE_MB * 1024 * 1024),
        "min_pct": config.BLOAT_RATIO_WARN,
    })
    for r in rows:
        bloat_pct = float(r["bloat_pct"] or 0)
        severity = "critical" if bloat_pct >= config.BLOAT_RATIO_CRIT else "warning"
        recs.append(Recommendation(
            category="index",
            severity=severity,
            title=f"Bloated index '{r['indexname']}' ({bloat_pct}% wasted)",
            description=(
                f"Index '{r['indexname']}' on '{r['tablename']}' is {r['index_size']} "
                f"with {r['wasted_size']} ({bloat_pct}%) wasted space."
            ),
            action=(
                "Rebuild the index to reclaim space. REINDEX CONCURRENTLY "
                "is non-blocking but requires extra disk space during rebuild."
            ),
            sql=f"REINDEX INDEX CONCURRENTLY {r['schemaname']}.{r['indexname']};",
        ))

    return recs


# ─────────────────────────────────────────────────────────────────────────────
# Block 2: TABLE BLOAT
# ─────────────────────────────────────────────────────────────────────────────

def check_bloat(conn) -> list[Recommendation]:
    recs: list[Recommendation] = []

    rows = _fetch(conn, queries.TABLE_BLOAT, {
        "min_bytes": int(config.BLOAT_MIN_SIZE_MB * 1024 * 1024),
        "min_pct": config.BLOAT_RATIO_WARN,
    })
    for r in rows:
        bloat_pct = float(r["bloat_pct"] or 0)
        severity = "critical" if bloat_pct >= config.BLOAT_RATIO_CRIT else "warning"
        table = f"{r['schemaname']}.{r['tablename']}"
        recs.append(Recommendation(
            category="bloat",
            severity=severity,
            title=f"Bloated table '{r['tablename']}' ({bloat_pct}% wasted)",
            description=(
                f"Table {table} is {r['table_size']} with {r['bloat_size']} "
                f"({bloat_pct}%) wasted. Autovacuum is not keeping up, "
                f"or the table has frequent UPDATE/DELETE patterns."
            ),
            action=(
                "Run VACUUM (or VACUUM FULL for severe bloat, but it locks the table). "
                "Consider tuning autovacuum_vacuum_scale_factor for this table."
            ),
            sql=(
                f"-- Non-blocking, reclaims space for reuse only:\n"
                f"VACUUM ANALYZE {table};\n\n"
                f"-- Or, if you can afford an exclusive lock and want to "
                f"return space to OS:\n"
                f"-- VACUUM FULL {table};"
            ),
        ))

    return recs


# ─────────────────────────────────────────────────────────────────────────────
# Block 3: HEAVY QUERIES
# ─────────────────────────────────────────────────────────────────────────────

def check_queries(conn) -> list[Recommendation]:
    recs: list[Recommendation] = []

    if not _pg_stat_statements_available(conn):
        recs.append(Recommendation(
            category="query",
            severity="warning",
            title="pg_stat_statements extension is not installed",
            description=(
                "Without pg_stat_statements, query-level analysis is impossible. "
                "Install the extension to enable workload monitoring."
            ),
            action=(
                "Add 'pg_stat_statements' to shared_preload_libraries in "
                "postgresql.conf, restart PostgreSQL, then run "
                "CREATE EXTENSION in each database."
            ),
            sql=(
                "-- In postgresql.conf:\n"
                "shared_preload_libraries = 'pg_stat_statements'\n\n"
                "-- After restart, in each database:\n"
                "CREATE EXTENSION pg_stat_statements;"
            ),
        ))
        return recs

    rows = _fetch(conn, queries.HEAVY_QUERIES)
    for r in rows:
        mean_ms = float(r["mean_ms"] or 0)
        pct_total = float(r["pct_total_time"] or 0)

        # Trigger if either: slow on average, OR consumes large share of total time
        if mean_ms < config.SLOW_QUERY_MEAN_MS_WARN and pct_total < config.QUERY_PCT_TOTAL_WARN:
            continue

        if mean_ms >= config.SLOW_QUERY_MEAN_MS_CRIT or pct_total >= 40:
            severity = "critical"
        else:
            severity = "warning"

        recs.append(Recommendation(
            category="query",
            severity=severity,
            title=f"Heavy query — {mean_ms} ms avg, {pct_total}% of total DB time",
            description=(
                f"Query [id {r['queryid']}] called {r['calls']:,} times, "
                f"avg {mean_ms} ms, total {r['total_sec']}s, "
                f"returns ~{r['avg_rows']} rows/call.\n"
                f"Preview: {r['query_preview']}"
            ),
            action=(
                "Run EXPLAIN (ANALYZE, BUFFERS) on a representative instance "
                "of this query. Look for Seq Scan on large tables, "
                "or large estimated vs actual row counts."
            ),
            sql=(
                f"-- Replace $1, $2, ... with realistic values before running:\n"
                f"EXPLAIN (ANALYZE, BUFFERS)\n{r['query_preview']};"
            ),
        ))

    return recs


# ─────────────────────────────────────────────────────────────────────────────
# Block 4: CONFIG
# ─────────────────────────────────────────────────────────────────────────────

def _to_mb(setting: str, unit: str) -> float | None:
    try:
        val = float(setting)
    except (TypeError, ValueError):
        return None
    unit = (unit or "").strip()
    if unit == "8kB":
        return val * 8 / 1024
    if unit == "kB":
        return val / 1024
    if unit == "MB":
        return val
    if unit == "GB":
        return val * 1024
    if unit == "" :  # dimensionless — assume bytes if huge, else None
        return val / 1024 / 1024 if val > 1_000_000 else None
    return None


def check_config(conn) -> list[Recommendation]:
    recs: list[Recommendation] = []
    rows = _fetch(conn, queries.CONFIG_PARAMS)
    params = {r["name"]: r for r in rows}
    ram = config.TOTAL_RAM_MB

    def get_mb(name: str) -> float | None:
        r = params.get(name)
        if r is None:
            return None
        return _to_mb(r["setting"], r["unit"] or "")

    # 4.1 shared_buffers — should be ~25% of RAM
    sb = get_mb("shared_buffers")
    if sb is not None:
        target = ram * config.SHARED_BUFFERS_TARGET_PCT / 100
        if sb < target * 0.7:
            recs.append(Recommendation(
                category="config",
                severity="warning",
                title=f"shared_buffers is too low ({sb:.0f} MB)",
                description=(
                    f"shared_buffers = {sb:.0f} MB, recommended ~{target:.0f} MB "
                    f"({config.SHARED_BUFFERS_TARGET_PCT}% of {ram} MB RAM). "
                    f"Low value forces PostgreSQL to read from disk more often."
                ),
                action="Increase shared_buffers in postgresql.conf and restart PostgreSQL.",
                sql=f"-- In postgresql.conf:\nshared_buffers = '{int(target)}MB'",
            ))

    # 4.2 effective_cache_size — planner hint, should be ~75% of RAM
    ecs = get_mb("effective_cache_size")
    if ecs is not None:
        target = ram * config.EFFECTIVE_CACHE_TARGET_PCT / 100
        if ecs < target * 0.5:
            recs.append(Recommendation(
                category="config",
                severity="info",
                title=f"effective_cache_size is too low ({ecs:.0f} MB)",
                description=(
                    f"effective_cache_size = {ecs:.0f} MB, recommended ~{target:.0f} MB. "
                    f"This is a planner hint (no memory allocated) and affects "
                    f"the cost of Index vs Seq Scan."
                ),
                action="Set effective_cache_size in postgresql.conf (no restart required, reload only).",
                sql=f"-- In postgresql.conf:\neffective_cache_size = '{int(target)}MB'",
            ))

    # 4.3 work_mem — too low causes disk sorts
    wm = get_mb("work_mem")
    if wm is not None and wm < 4:
        recs.append(Recommendation(
            category="config",
            severity="info",
            title=f"work_mem is very low ({wm:.0f} MB)",
            description=(
                f"work_mem = {wm:.0f} MB. Sort and hash operations may spill to disk."
            ),
            action=(
                "Increase work_mem cautiously — it applies per operation, "
                "and a single query can use it multiple times."
            ),
            sql="-- In postgresql.conf:\nwork_mem = '16MB'",
        ))

    # 4.4 checkpoint_completion_target — should be >= 0.7
    cct = params.get("checkpoint_completion_target")
    if cct:
        try:
            val = float(cct["setting"])
            if val < 0.7:
                recs.append(Recommendation(
                    category="config",
                    severity="info",
                    title=f"checkpoint_completion_target is low ({val})",
                    description=(
                        f"checkpoint_completion_target = {val}. "
                        f"Low values cause IO spikes during checkpoints."
                    ),
                    action="Set checkpoint_completion_target = 0.9 in postgresql.conf.",
                    sql="-- In postgresql.conf:\ncheckpoint_completion_target = 0.9",
                ))
        except ValueError:
            pass

    # 4.5 autovacuum disabled
    av = params.get("autovacuum")
    if av and av["setting"] == "off":
        recs.append(Recommendation(
            category="config",
            severity="critical",
            title="autovacuum is DISABLED",
            description=(
                "autovacuum = off. This is dangerous — dead tuples will accumulate, "
                "tables will bloat, and statistics will go stale."
            ),
            action="Enable autovacuum in postgresql.conf and reload configuration.",
            sql="-- In postgresql.conf:\nautovacuum = on",
        ))

    # 4.6 pg_stat_statements fill level
    fill_rows = _fetch(conn, queries.PG_STAT_STATEMENTS_FILL)
    if fill_rows:
        f = fill_rows[0]
        current = int(f["current_count"] or 0)
        maximum = int(f["max_count"] or 0)
        if maximum > 0:
            pct = current / maximum * 100
            if pct >= config.PG_STAT_STATEMENTS_FILL_WARN:
                recs.append(Recommendation(
                    category="config",
                    severity="warning",
                    title=f"pg_stat_statements is {pct:.0f}% full ({current}/{maximum})",
                    description=(
                        f"When pg_stat_statements reaches its limit, new query stats "
                        f"evict the least-used ones, making analysis incomplete."
                    ),
                    action=(
                        "Either increase pg_stat_statements.max in postgresql.conf "
                        "(requires restart) or reset statistics now."
                    ),
                    sql=(
                        "-- Option A: reset stats (loses history):\n"
                        "SELECT pg_stat_statements_reset();\n\n"
                        "-- Option B: in postgresql.conf (requires restart):\n"
                        "-- pg_stat_statements.max = 10000"
                    ),
                ))

    return recs


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────────────────────────────────────

CHECKS = [
    ("indexes", check_indexes),
    ("bloat",   check_bloat),
    ("queries", check_queries),
    ("config",  check_config),
]


def run_all_checks(conn) -> tuple[list[Recommendation], list[str]]:
    results: list[Recommendation] = []
    errors: list[str] = []
    for name, fn in CHECKS:
        try:
            results.extend(fn(conn))
        except Exception as e:
            errors.append(f"{name}: {e}")
            print(f"[checks] {name} failed: {e}")
    return results, errors
