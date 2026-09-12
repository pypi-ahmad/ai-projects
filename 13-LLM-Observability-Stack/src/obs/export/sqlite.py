"""SQLite export: traces, spans, usage tables. See docs/SCHEMA.md.

Writes only - reads live in query.py. This file must not compute pricing
itself (it calls export/common.py's priced_usage, which defers to
metrics/pricing.py) and must not know about JSONL (jsonl.py is the sibling
writer). Next file to read: query.py (how these tables get read back into
Trace/Span objects).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

from obs.export.common import priced_usage

if TYPE_CHECKING:
    from obs.trace.models import Trace

DEFAULT_DB_PATH = Path("data/obs.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS traces (
    trace_id TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    route TEXT,
    attrs TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_traces_ts ON traces(ts);
CREATE INDEX IF NOT EXISTS idx_traces_route ON traces(route);

CREATE TABLE IF NOT EXISTS spans (
    span_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    parent_id TEXT,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    provider TEXT,
    model TEXT,
    ts TEXT NOT NULL,
    start_ns INTEGER NOT NULL,
    end_ns INTEGER,
    latency_ms REAL,
    status TEXT NOT NULL,
    error TEXT,
    attrs TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(trace_id) REFERENCES traces(trace_id)
);
CREATE INDEX IF NOT EXISTS idx_spans_trace ON spans(trace_id);
CREATE INDEX IF NOT EXISTS idx_spans_model ON spans(model);
CREATE INDEX IF NOT EXISTS idx_spans_ts ON spans(ts);
CREATE INDEX IF NOT EXISTS idx_spans_status ON spans(status);

CREATE TABLE IF NOT EXISTS usage (
    span_id TEXT PRIMARY KEY,
    in_tokens INTEGER,
    out_tokens INTEGER,
    cost_est REAL,
    pricing TEXT NOT NULL,
    ttft_ms REAL,
    FOREIGN KEY(span_id) REFERENCES spans(span_id)
);
"""


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA)


class SqliteExporter:
    """Callable exporter: register with obs.trace.register_exporter."""

    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        init_db(db_path)

    def __call__(self, trace: Trace) -> None:
        # traces.ts comes from the root span's ts (falls back to spans[0]
        # if no span has parent_id=None, e.g. a hand-built ingested trace
        # that never marked one root). traces.trace_id is PRIMARY KEY, so a
        # duplicate trace_id raises sqlite3.IntegrityError here rather than
        # silently overwriting - callers that need idempotent re-ingest
        # (see api/app.py's /v1/ingest) check for an existing trace first.
        root = next((s for s in trace.spans if s.ctx.parent_id is None), trace.spans[0])
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO traces (trace_id, ts, route, attrs) VALUES (?, ?, ?, ?)",
                (
                    trace.trace_id,
                    root.ts,
                    trace.attrs.get("route"),
                    json.dumps(trace.attrs),
                ),
            )
            for span in trace.spans:
                conn.execute(
                    """INSERT INTO spans
                       (span_id, trace_id, parent_id, name, kind, provider, model, ts,
                        start_ns, end_ns, latency_ms, status, error, attrs)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        span.ctx.span_id,
                        trace.trace_id,
                        span.ctx.parent_id,
                        span.name,
                        span.kind,
                        span.provider,
                        span.model,
                        span.ts,
                        span.start_ns,
                        span.end_ns,
                        span.latency_ms,
                        span.status,
                        span.error,
                        json.dumps(span.attrs),
                    ),
                )
                usage = priced_usage(span)
                if usage is not None:
                    conn.execute(
                        """INSERT INTO usage
                           (span_id, in_tokens, out_tokens, cost_est, pricing, ttft_ms)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            span.ctx.span_id,
                            usage["in_tokens"],
                            usage["out_tokens"],
                            usage["cost_est"],
                            usage["pricing"],
                            usage["ttft_ms"],
                        ),
                    )
