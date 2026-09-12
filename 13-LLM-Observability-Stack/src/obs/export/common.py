"""Shared span->row conversion used by both JsonlExporter and SqliteExporter.

Exists so pricing/flattening logic lives in exactly one place instead of
being duplicated across the two exporter implementations. priced_usage()
is where cost_est actually gets computed for storage (not on the live
Span/Usage models - see docs/SCHEMA.md's note on "PRICED"/"UNPRICED" being
a storage-layer concept).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from obs.metrics import estimate_cost

if TYPE_CHECKING:
    from obs.trace.models import Span


def priced_usage(span: Span) -> dict[str, Any] | None:
    if span.usage is None:
        return None
    cost_est, pricing = estimate_cost(
        span.model,
        span.usage.in_tokens,
        span.usage.out_tokens,
        existing_cost=span.usage.cost_est,
    )
    return {
        "in_tokens": span.usage.in_tokens,
        "out_tokens": span.usage.out_tokens,
        "cost_est": cost_est,
        "pricing": pricing,
        "ttft_ms": span.usage.ttft_ms,
    }


def span_row(trace_id: str, span: Span) -> dict[str, Any]:
    return {
        "trace_id": trace_id,
        "span_id": span.ctx.span_id,
        "parent_id": span.ctx.parent_id,
        "name": span.name,
        "kind": span.kind,
        "provider": span.provider,
        "model": span.model,
        "ts": span.ts,
        "start_ns": span.start_ns,
        "end_ns": span.end_ns,
        "latency_ms": span.latency_ms,
        "status": span.status,
        "error": span.error,
        "usage": priced_usage(span),
        "attrs": span.attrs,
    }
