import os

# Database connection
DB_HOST = os.getenv("DB_HOST", "postgres")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "dvdrental")
DB_USER = os.getenv("DB_USER", "admin")
DB_PASSWORD = os.getenv("DB_PASSWORD", "admin")

# Analyzer settings
ANALYSIS_INTERVAL_SEC = int(os.getenv("ANALYSIS_INTERVAL_SEC", "900"))  # 15 min
ADVISOR_PORT = int(os.getenv("ADVISOR_PORT", "9188"))
TOTAL_RAM_MB = int(os.getenv("TOTAL_RAM_MB", "8192"))

# Thresholds — all can be overridden via env
CACHE_HIT_RATIO_WARN = float(os.getenv("CACHE_HIT_RATIO_WARN", "0.90"))
CACHE_HIT_RATIO_CRIT = float(os.getenv("CACHE_HIT_RATIO_CRIT", "0.80"))

DEAD_RATIO_WARN = float(os.getenv("DEAD_RATIO_WARN", "0.15"))   # 15% dead tuples
DEAD_RATIO_CRIT = float(os.getenv("DEAD_RATIO_CRIT", "0.30"))

SEQ_SCAN_PCT_WARN = float(os.getenv("SEQ_SCAN_PCT_WARN", "0.70"))  # 70% seq scans
MIN_TABLE_ROWS = int(os.getenv("MIN_TABLE_ROWS", "5000"))           # ignore small tables
MIN_SEQ_SCANS = int(os.getenv("MIN_SEQ_SCANS", "50"))               # ignore rarely scanned

SLOW_QUERY_WARN_MS = float(os.getenv("SLOW_QUERY_WARN_MS", "500"))
SLOW_QUERY_CRIT_MS = float(os.getenv("SLOW_QUERY_CRIT_MS", "2000"))

LONG_TX_WARN_SEC = int(os.getenv("LONG_TX_WARN_SEC", "60"))
LONG_TX_CRIT_SEC = int(os.getenv("LONG_TX_CRIT_SEC", "300"))

PG_STAT_STATEMENTS_MAX_WARN = float(os.getenv("PG_STAT_STATEMENTS_MAX_WARN", "0.80"))
