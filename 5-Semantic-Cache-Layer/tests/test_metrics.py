from datetime import datetime, timedelta, timezone

from src.metrics.aggregator import aggregate, read_events
from src.metrics.logger import MetricsLogger


def test_log_appends_one_json_line_per_call(tmp_path):
    path = tmp_path / "metrics.jsonl"
    logger = MetricsLogger(path=path)

    logger.log(event="put", namespace="demo", latency_ms=12.3, embed_ms=10.0)
    logger.log(event="hit", namespace="demo", score=0.95, latency_ms=5.0, exact=True)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2


def test_read_events_roundtrips_fields(tmp_path):
    path = tmp_path / "metrics.jsonl"
    logger = MetricsLogger(path=path)
    logger.log(event="hit", namespace="demo", score=0.95, latency_ms=5.0, embed_ms=3.0, exact=False)

    events = read_events(path=path)

    assert len(events) == 1
    event = events[0]
    assert event.namespace == "demo"
    assert event.event == "hit"
    assert event.score == 0.95
    assert event.exact is False


def test_read_events_filters_by_since(tmp_path):
    path = tmp_path / "metrics.jsonl"
    old_line = '{"ts": "2020-01-01T00:00:00Z", "namespace": "demo", "event": "hit"}'
    path.write_text(old_line + "\n", encoding="utf-8")
    logger = MetricsLogger(path=path)
    logger.log(event="miss", namespace="demo")

    recent = read_events(path=path, since=datetime.now(timezone.utc) - timedelta(hours=1))

    assert len(recent) == 1
    assert recent[0].event == "miss"


def test_aggregate_computes_hit_rate_per_namespace():
    path_events = [
        _event("demo", "hit"),
        _event("demo", "hit"),
        _event("demo", "miss"),
        _event("other", "miss"),
    ]

    stats = aggregate(path_events)

    assert stats["demo"].hits == 2
    assert stats["demo"].misses == 1
    assert stats["demo"].hit_rate == 2 / 3
    assert stats["other"].hit_rate == 0.0


def test_aggregate_hit_rate_is_none_with_no_hits_or_misses():
    stats = aggregate([_event("demo", "put"), _event("demo", "reject")])

    assert stats["demo"].hit_rate is None
    assert stats["demo"].puts == 1
    assert stats["demo"].rejects == 1


def _event(namespace: str, event: str):
    from src.metrics.logger import MetricsEvent

    return MetricsEvent(ts=datetime.now(timezone.utc), namespace=namespace, event=event)
