import os

# ── Database connection ──────────────────────────────────────────────────────
DB_HOST = os.getenv("DB_HOST", "postgres")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "dvdrental")
DB_USER = os.getenv("DB_USER", "admin")
DB_PASSWORD = os.getenv("DB_PASSWORD", "password")

# ── Service settings ─────────────────────────────────────────────────────────
ANALYSIS_INTERVAL_SEC = int(os.getenv("ANALYSIS_INTERVAL_SEC", "900"))   # 15 min
ADVISOR_PORT = int(os.getenv("ADVISOR_PORT", "9188"))
TOTAL_RAM_MB = int(os.getenv("TOTAL_RAM_MB", "8192"))
STATEMENT_TIMEOUT_MS = int(os.getenv("STATEMENT_TIMEOUT_MS", "5000"))


SEQ_SCAN_PCT_WARN = float(os.getenv("SEQ_SCAN_PCT_WARN", "70"))
MIN_TABLE_ROWS = int(os.getenv("MIN_TABLE_ROWS", "5000"))
MIN_SEQ_SCANS = int(os.getenv("MIN_SEQ_SCANS", "50"))
UNUSED_INDEX_MIN_MB = float(os.getenv("UNUSED_INDEX_MIN_MB", "1"))

# ── Bloat thresholds ─────────────────────────────────────────────────────────
BLOAT_RATIO_WARN = float(os.getenv("BLOAT_RATIO_WARN", "20"))     # %
BLOAT_RATIO_CRIT = float(os.getenv("BLOAT_RATIO_CRIT", "40"))     # %
BLOAT_MIN_SIZE_MB = float(os.getenv("BLOAT_MIN_SIZE_MB", "10"))

# ── Query thresholds ─────────────────────────────────────────────────────────
SLOW_QUERY_MEAN_MS_WARN = float(os.getenv("SLOW_QUERY_MEAN_MS_WARN", "500"))
SLOW_QUERY_MEAN_MS_CRIT = float(os.getenv("SLOW_QUERY_MEAN_MS_CRIT", "2000"))
QUERY_PCT_TOTAL_WARN = float(os.getenv("QUERY_PCT_TOTAL_WARN", "20"))  # % of total DB time

# ── Config check ─────────────────────────────────────────────────────────────


SHARED_BUFFERS_TARGET_PCT = float(os.getenv("SHARED_BUFFERS_TARGET_PCT", "25"))
EFFECTIVE_CACHE_TARGET_PCT = float(os.getenv("EFFECTIVE_CACHE_TARGET_PCT", "75"))
PG_STAT_STATEMENTS_FILL_WARN = float(os.getenv("PG_STAT_STATEMENTS_FILL_WARN", "80"))
