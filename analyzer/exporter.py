from prometheus_client import Gauge, CollectorRegistry, generate_latest, CONTENT_TYPE_LATEST

registry = CollectorRegistry()

_total = Gauge(
    "pg_advisor_recommendations_total",
    "Number of open recommendations by category and severity",
    ["category", "severity"],
    registry=registry,
)

_active = Gauge(
    "pg_advisor_recommendation_active",
    "Each open recommendation as a labelled metric (value=1)",
    ["category", "severity", "title"],
    registry=registry,
)


def update_metrics(open_recs: list[dict]):
    """
    Rebuild Prometheus metrics from the current list of open recommendations.
    Called after every analysis cycle.
    """
    _total.clear()
    _active.clear()

    counts: dict[tuple, int] = {}
    for rec in open_recs:
        key = (rec["category"], rec["severity"])
        counts[key] = counts.get(key, 0) + 1
        _active.labels(
            category=rec["category"],
            severity=rec["severity"],
            title=rec["title"],
        ).set(1)

    for (cat, sev), count in counts.items():
        _total.labels(category=cat, severity=sev).set(count)


def metrics_output() -> tuple[bytes, str]:
    return generate_latest(registry), CONTENT_TYPE_LATEST
