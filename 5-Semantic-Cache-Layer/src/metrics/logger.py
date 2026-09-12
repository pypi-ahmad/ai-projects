"""Append-only JSONL event log for cache activity (docs/METRICS.md).

One JSON object per line via MetricsEvent.model_dump_json() -- ts,
namespace, event (hit|miss|put|evict|reject), and event-specific optional
fields (score, latency_ms, embed_ms, exact).
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

DEFAULT_METRICS_PATH = Path("data/cache/metrics.jsonl")

EventType = Literal["hit", "miss", "put", "evict", "reject"]


class MetricsEvent(BaseModel):
    ts: datetime
    namespace: str
    event: EventType
    score: float | None = None
    latency_ms: float | None = None
    embed_ms: float | None = None
    exact: bool | None = None


class MetricsLogger:
    def __init__(self, path: Path = DEFAULT_METRICS_PATH):
        self._path = path

    def log(
        self,
        *,
        event: EventType,
        namespace: str,
        score: float | None = None,
        latency_ms: float | None = None,
        embed_ms: float | None = None,
        exact: bool | None = None,
    ) -> None:
        record = MetricsEvent(
            ts=datetime.now(timezone.utc),
            namespace=namespace,
            event=event,
            score=score,
            latency_ms=latency_ms,
            embed_ms=embed_ms,
            exact=exact,
        )
        # Opens, appends, and closes per call -- no explicit lock between
        # concurrent writers (e.g. the CLI and a running Streamlit process
        # both logging to the same path).
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(record.model_dump_json() + "\n")
