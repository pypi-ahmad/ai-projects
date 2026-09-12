"""Rolling window stats per route+model, computed on read (v1 - no materialized table).

Per docs/ALERTS.md: no incremental rollup table yet; every evaluation pass
re-queries spans/traces/usage and aggregates in Python. Read-only - must
not write to the alerts table (store.py owns writes) or make evaluation
decisions (rules.py owns thresholds). Next file to read: rules.py.
"""

from __future__ import annotations

import sqlite3
import statistics
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from obs.export.sqlite import DEFAULT_DB_PATH

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class WindowStats:
    n: int
    error_rate: float
    p50_latency_ms: float | None
    p95_latency_ms: float | None
    avg_tokens: float | None
    avg_cost: float | None
    ttft_p50_ms: float | None
    unpriced_fraction: float | None
    trace_ids: list[str] = field(default_factory=list)


_MIN_SAMPLES_FOR_QUANTILES = 2


def percentile(values: list[float], pct: int) -> float | None:
    if not values:
        return None
    if len(values) < _MIN_SAMPLES_FOR_QUANTILES:
        return values[0]
    # statistics.quantiles(n=100) returns 99 cut points, where index i-1
    # approximates the i-th percentile (verified empirically: index 49 on
    # 1..100 gives ~50.5, the true median). Hence pct-1 below.
    quantiles = statistics.quantiles(sorted(values), n=100, method="inclusive")
    return quantiles[max(1, min(99, pct)) - 1]


def fetch_window_rows(
    route: str | None,
    model: str | None,
    *,
    limit: int | None = None,
    since: str | None = None,
    until: str | None = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> list[sqlite3.Row]:
    """Spans for a route+model, newest first, left-joined with usage."""
    clauses = ["t.route IS ?", "s.model IS ?"]
    params: list[object] = [route, model]
    if since is not None:
        clauses.append("s.ts >= ?")
        params.append(since)
    if until is not None:
        clauses.append("s.ts < ?")
        params.append(until)
    where = " AND ".join(clauses)
    sql = f"""
        SELECT s.span_id, s.trace_id, s.status, s.latency_ms,
               u.in_tokens, u.out_tokens, u.cost_est, u.ttft_ms, u.pricing
        FROM spans s
        JOIN traces t ON s.trace_id = t.trace_id
        LEFT JOIN usage u ON u.span_id = s.span_id
        WHERE {where}
        ORDER BY s.ts DESC
    """  # noqa: S608 - clauses are fixed strings, values are bound params
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(sql, params).fetchall()


def distinct_route_models(
    *, since: str | None = None, db_path: Path = DEFAULT_DB_PATH
) -> list[tuple[str | None, str | None]]:
    """(route, model) pairs with any span activity, optionally since a timestamp.

    Excludes spans with no model set (e.g. a plain container span) - "per
    route+model" rules aren't meaningful for a span that names no model.
    """
    clauses = ["s.model IS NOT NULL"]
    params: list[str] = []
    if since is not None:
        clauses.append("s.ts >= ?")
        params.append(since)
    where = " AND ".join(clauses)
    sql = f"""
        SELECT DISTINCT t.route, s.model
        FROM spans s JOIN traces t ON s.trace_id = t.trace_id
        WHERE {where}
    """  # noqa: S608 - fixed clause, values are bound params
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [(r[0], r[1]) for r in rows]


def earliest_ts(
    route: str | None, model: str | None, *, db_path: Path = DEFAULT_DB_PATH
) -> str | None:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """SELECT MIN(s.ts) FROM spans s JOIN traces t ON s.trace_id = t.trace_id
               WHERE t.route IS ? AND s.model IS ?""",
            (route, model),
        ).fetchone()
    return row[0] if row else None


def compute_window_stats(rows: list[sqlite3.Row], *, trace_id_sample: int = 5) -> WindowStats:
    n = len(rows)
    if n == 0:
        return WindowStats(
            n=0,
            error_rate=0.0,
            p50_latency_ms=None,
            p95_latency_ms=None,
            avg_tokens=None,
            avg_cost=None,
            ttft_p50_ms=None,
            unpriced_fraction=None,
        )

    errors = sum(1 for r in rows if r["status"] == "error")
    latencies = [r["latency_ms"] for r in rows if r["latency_ms"] is not None]
    token_totals = [
        r["in_tokens"] + r["out_tokens"]
        for r in rows
        if r["in_tokens"] is not None and r["out_tokens"] is not None
    ]
    costs = [r["cost_est"] for r in rows if r["cost_est"] is not None]
    ttfts = [r["ttft_ms"] for r in rows if r["ttft_ms"] is not None]
    priced_rows = [r for r in rows if r["pricing"] is not None]
    unpriced = sum(1 for r in priced_rows if r["pricing"] == "UNPRICED")

    return WindowStats(
        n=n,
        error_rate=errors / n,
        p50_latency_ms=percentile(latencies, 50),
        p95_latency_ms=percentile(latencies, 95),
        avg_tokens=statistics.fmean(token_totals) if token_totals else None,
        avg_cost=statistics.fmean(costs) if costs else None,
        ttft_p50_ms=percentile(ttfts, 50),
        unpriced_fraction=(unpriced / len(priced_rows)) if priced_rows else None,
        # dict.fromkeys dedupes while preserving first-seen order (rows are
        # newest-first from the query), then take the first N as a sample.
        trace_ids=list(dict.fromkeys(r["trace_id"] for r in rows))[:trace_id_sample],
    )
