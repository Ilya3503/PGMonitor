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
    counts = {}

    # reset logic via overwrite, not clear
    for rec in open_recs:
        key = (rec["category"], rec["severity"])
        counts[key] = counts.get(key, 0) + 1

    # overwrite totals completely
    for label_values in list(_total._metrics.keys()):
        _total.remove(*label_values)

    for (cat, sev), count in counts.items():
        _total.labels(category=cat, severity=sev).set(count)

    # rebuild active completely
    for label_values in list(_active._metrics.keys()):
        _active.remove(*label_values)

    for rec in open_recs:
        _active.labels(
            category=rec["category"],
            severity=rec["severity"],
            title=rec["title"],
        ).set(1)

def metrics_output() -> tuple[bytes, str]:
    return generate_latest(registry), CONTENT_TYPE_LATEST
