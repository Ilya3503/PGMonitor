"""
Prometheus exporter. Pure stateless — metrics are rebuilt from
the latest in-memory recommendations after every analysis cycle.
"""

from prometheus_client import (
    Gauge, CollectorRegistry, generate_latest, CONTENT_TYPE_LATEST,
)

registry = CollectorRegistry()

_total = Gauge(
    "pg_advisor_recommendations_total",
    "Number of recommendations grouped by category and severity",
    ["category", "severity"],
    registry=registry,
)

_active = Gauge(
    "pg_advisor_recommendation",
    "Each recommendation as a separate time series (value = 1)",
    ["category", "severity", "title"],
    registry=registry,
)

_last_run_ts = Gauge(
    "pg_advisor_last_run_timestamp_seconds",
    "Unix timestamp of the most recent analysis run",
    registry=registry,
)

_last_run_duration = Gauge(
    "pg_advisor_last_run_duration_seconds",
    "Duration of the most recent analysis run, in seconds",
    registry=registry,
)

_last_run_errors = Gauge(
    "pg_advisor_last_run_errors_total",
    "Number of analysis blocks that failed in the most recent run",
    registry=registry,
)


def update_metrics(
    recommendations: list[dict],
    last_run_ts: float,
    last_run_duration: float,
    errors: int,
):
    _total.clear()
    _active.clear()

    counts: dict[tuple, int] = {}
    for rec in recommendations:
        key = (rec["category"], rec["severity"])
        counts[key] = counts.get(key, 0) + 1
        _active.labels(
            category=rec["category"],
            severity=rec["severity"],
            title=rec["title"],
        ).set(1)

    for (cat, sev), count in counts.items():
        _total.labels(category=cat, severity=sev).set(count)

    _last_run_ts.set(last_run_ts)
    _last_run_duration.set(last_run_duration)
    _last_run_errors.set(errors)


def metrics_output() -> tuple[bytes, str]:
    return generate_latest(registry), CONTENT_TYPE_LATEST
