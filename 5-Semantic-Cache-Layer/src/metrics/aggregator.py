"""Aggregate data/cache/metrics.jsonl into per-namespace hit rate over a
window (docs/METRICS.md). Read-only -- src/metrics/logger.py writes.
"""

from collections import defaultdict
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from src.metrics.logger import DEFAULT_METRICS_PATH, MetricsEvent


class NamespaceStats(BaseModel):
    namespace: str
    hits: int
    misses: int
    puts: int
    evictions: int
    rejects: int
    hit_rate: float | None  # None if hits + misses == 0 -- not zero, which would imply a measured 0%


def read_events(path: Path = DEFAULT_METRICS_PATH, *, since: datetime | None = None) -> list[MetricsEvent]:
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        event = MetricsEvent.model_validate_json(line)
        if since is not None and event.ts < since:
            continue
        events.append(event)
    return events


def aggregate(events: list[MetricsEvent]) -> dict[str, NamespaceStats]:
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for event in events:
        counts[event.namespace][event.event] += 1

    result: dict[str, NamespaceStats] = {}
    for namespace, c in counts.items():
        hits, misses = c.get("hit", 0), c.get("miss", 0)
        total = hits + misses
        result[namespace] = NamespaceStats(
            namespace=namespace,
            hits=hits,
            misses=misses,
            puts=c.get("put", 0),
            evictions=c.get("evict", 0),
            rejects=c.get("reject", 0),
            hit_rate=(hits / total) if total > 0 else None,
        )
    return result
