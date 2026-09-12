"""Read helpers over the tables SqliteExporter writes.

Read-only, SQLite-only (no JSONL reader exists - see jsonl.py's module
docstring). get_trace reconstructs a full pydantic Trace; query() returns
loosely-typed dicts instead, since its rows are a flattened join, not a
single model. Next file to read: api/app.py (the only caller of both).
"""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING, Any

from obs.export.sqlite import DEFAULT_DB_PATH
from obs.trace.models import Span, SpanContext, Trace, Usage

if TYPE_CHECKING:
    from pathlib import Path


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_span(row: sqlite3.Row, usage_row: sqlite3.Row | None) -> Span:
    usage = None
    if usage_row is not None:
        usage = Usage(
            in_tokens=usage_row["in_tokens"],
            out_tokens=usage_row["out_tokens"],
            cost_est=usage_row["cost_est"],
            ttft_ms=usage_row["ttft_ms"],
        )
    return Span(
        ctx=SpanContext(
            trace_id=row["trace_id"], span_id=row["span_id"], parent_id=row["parent_id"]
        ),
        name=row["name"],
        kind=row["kind"],
        provider=row["provider"],
        model=row["model"],
        ts=row["ts"],
        start_ns=row["start_ns"],
        end_ns=row["end_ns"],
        latency_ms=row["latency_ms"],
        status=row["status"],
        error=row["error"],
        usage=usage,
        attrs=json.loads(row["attrs"]),
    )


def get_trace(trace_id: str, *, db_path: Path = DEFAULT_DB_PATH) -> Trace | None:
    with _connect(db_path) as conn:
        trace_row = conn.execute("SELECT * FROM traces WHERE trace_id = ?", (trace_id,)).fetchone()
        if trace_row is None:
            return None
        span_rows = conn.execute(
            "SELECT * FROM spans WHERE trace_id = ? ORDER BY start_ns", (trace_id,)
        ).fetchall()
        spans = []
        for span_row in span_rows:
            usage_row = conn.execute(
                "SELECT * FROM usage WHERE span_id = ?", (span_row["span_id"],)
            ).fetchone()
            spans.append(_row_to_span(span_row, usage_row))
    return Trace(trace_id=trace_id, spans=spans, attrs=json.loads(trace_row["attrs"]))


def query(
    *,
    route: str | None = None,
    model: str | None = None,
    since: str | None = None,
    status: str | None = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    """Matching spans (as dicts), joined with their trace's route and usage.

    All filters optional. Includes in_tokens/out_tokens/cost_est/pricing/
    ttft_ms (null when the span has no usage row).
    """
    clauses = []
    params: list[str] = []
    if route is not None:
        clauses.append("t.route = ?")
        params.append(route)
    if model is not None:
        clauses.append("s.model = ?")
        params.append(model)
    if since is not None:
        clauses.append("s.ts >= ?")
        params.append(since)
    if status is not None:
        clauses.append("s.status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT s.*, t.route AS trace_route,
               u.in_tokens, u.out_tokens, u.cost_est, u.pricing, u.ttft_ms
        FROM spans s
        JOIN traces t ON s.trace_id = t.trace_id
        LEFT JOIN usage u ON u.span_id = s.span_id
        {where}
        ORDER BY s.ts DESC
    """  # noqa: S608 - clauses are fixed strings, values are bound params
    with _connect(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]
