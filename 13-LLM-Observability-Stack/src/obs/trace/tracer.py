"""Tracer core: nested spans via contextvars, in-memory export, exporter hooks.

Responsible for span/trace lifecycle (creation, nesting, timing, export
dispatch) and nothing else - it must not know about SQLite, JSONL, pricing,
or HTTP; those live in export/, metrics/, and api/ and only interact with
this module through register_exporter/export_trace and the public Trace
model. Next file to read: models.py (what a Span/Trace actually holds), or
export/sqlite.py + export/jsonl.py (what consumes what this module produces).

Usage:
    with Tracer.start("request") as span:
        span.set(model=..., provider=...)
        with span.child("generate"):
            ...
        span.set_usage(in_tokens=10, out_tokens=20)
"""

from __future__ import annotations

import contextvars
import logging
import os
import time
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal, Self

from obs.trace.models import Span, SpanContext, Trace, Usage
from obs.trace.redact import redact

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType

SpanKind = Literal["client", "internal"]

logger = logging.getLogger(__name__)

# contextvars, not plain module globals: each asyncio task/thread gets its
# own value, so concurrent requests in the same process (e.g. the FastAPI
# server handling two calls at once) each see their own current span/trace
# without one clobbering the other's. This is what lets Tracer.start() find
# its parent implicitly - see the module docstring's usage example.
_current_span: contextvars.ContextVar[SpanHandle | None] = contextvars.ContextVar(
    "obs_current_span", default=None
)
_current_trace: contextvars.ContextVar[Trace | None] = contextvars.ContextVar(
    "obs_current_trace", default=None
)

# Process-lifetime state, not persisted anywhere on its own - reset only by
# calling clear_finished_traces()/restarting the process, or (in tests) by
# monkeypatching _exporters directly.
_finished_traces: list[Trace] = []
_exporters: list[Callable[[Trace], None]] = []


def register_exporter(fn: Callable[[Trace], None]) -> None:
    """Register a callable invoked with each finished Trace."""
    _exporters.append(fn)


def get_finished_traces() -> list[Trace]:
    return list(_finished_traces)


def clear_finished_traces() -> None:
    """For test isolation between cases."""
    _finished_traces.clear()


def _run_exporters(trace: Trace) -> None:
    # Each exporter's failure is swallowed and logged, not re-raised: one
    # broken exporter (e.g. a full disk for SqliteExporter) must not stop
    # the others from running, and must never propagate into the traced
    # code's own control flow (SpanHandle.__exit__ calls this after the
    # traced `with` block has already finished/raised on its own terms).
    for exporter in _exporters:
        try:
            exporter(trace)
        except Exception:
            logger.warning("exporter failed", exc_info=True)


def export_trace(trace: Trace) -> None:
    """Export an already-built Trace (e.g. ingested from another service)
    through the registered exporters, without creating any new spans.

    This is the entry point for /v1/ingest: a Trace built entirely outside
    this process (no SpanHandle/Tracer.start involved) still needs to reach
    the same exporters a locally-created trace does.
    """
    _finished_traces.append(trace)
    _run_exporters(trace)


class SpanHandle:
    """Context-manager handle returned by Tracer.start / span.child."""

    def __init__(self, span: Span, trace: Trace, *, is_root: bool) -> None:
        self._span = span
        self._trace = trace
        self._is_root = is_root
        self._span_token: contextvars.Token[SpanHandle | None] | None = None
        self._trace_token: contextvars.Token[Trace | None] | None = None

    @property
    def span_id(self) -> str:
        return self._span.ctx.span_id

    @property
    def trace_id(self) -> str:
        return self._span.ctx.trace_id

    def set(self, **kwargs: Any) -> None:
        # A name matching a real Span field (e.g. model=, provider=) sets
        # that field; anything else falls through to the free-form attrs
        # dict. This lets callers pass arbitrary metadata without this
        # method needing to know every possible attrs key in advance.
        for key, value in kwargs.items():
            if key in Span.model_fields:
                setattr(self._span, key, value)
            else:
                self._span.attrs[key] = value

    def set_usage(self, **kwargs: Any) -> None:
        self._span.usage = Usage(**kwargs)

    def set_trace(self, **kwargs: Any) -> None:
        """Set trace-level attrs (tenant, route, prompt_name, prompt_version, ...)."""
        self._trace.attrs.update(kwargs)

    def set_prompt(self, text: str | None) -> None:
        # The actual privacy gate (docs/PRIVACY.md): hash+preview are always
        # attached; the raw text is kept only if OBS_STORE_PROMPTS is set to
        # "true" (case-insensitive) *at the moment this call runs*, checked
        # fresh each time rather than cached - so flipping the env var takes
        # effect on the next span, not retroactively.
        digest, preview = redact(text)
        self._span.attrs["prompt_hash"] = digest
        self._span.attrs["prompt_preview"] = preview
        if os.environ.get("OBS_STORE_PROMPTS", "").lower() == "true":
            self._span.attrs["full_prompt"] = text

    def child(self, name: str, *, kind: SpanKind = "internal") -> SpanHandle:
        # Delegates straight to Tracer.start(): by the time child() is
        # called, __enter__ has already made `self` the current span via
        # the contextvar, so start() will find it as the parent on its own.
        return Tracer.start(name, kind=kind)

    def __enter__(self) -> Self:
        self._span_token = _current_span.set(self)
        if self._is_root:
            self._trace_token = _current_trace.set(self._trace)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        # Runs for every span, root or child. An exception here always
        # propagates further (return False, never suppressed) - so if the
        # traced code raises inside a child span, that same exception is
        # still live when the *parent* span's __exit__ runs too, and the
        # parent also gets marked status="error". A single failure inside
        # nested spans marks the whole chain up to the root as error, by
        # design - it's the intended way to represent "the request failed".
        end_ns = time.monotonic_ns()
        self._span.end_ns = end_ns
        self._span.latency_ms = (end_ns - self._span.start_ns) / 1_000_000
        if exc is not None:
            self._span.status = "error"
            self._span.error = str(exc)
        self._trace.spans.append(self._span)

        if self._span_token is not None:
            _current_span.reset(self._span_token)
        if self._is_root:
            # Only the root span triggers export - children just append
            # themselves to trace.spans and wait. This relies on nested
            # `with` blocks always closing inner-to-outer, so every child's
            # __exit__ has already run and appended its span by the time
            # the root's __exit__ (this branch) fires.
            if self._trace_token is not None:
                _current_trace.reset(self._trace_token)
            export_trace(self._trace)
        return False  # never suppress the exception


class Tracer:
    @staticmethod
    def start(name: str, *, kind: SpanKind = "internal") -> SpanHandle:
        # No current span in this context -> this call starts a brand new
        # trace (root). A current span present -> this becomes its child,
        # in the *same* trace. This is what makes span.child() and a bare
        # nested Tracer.start() call equivalent - both just check the same
        # contextvar.
        parent = _current_span.get()
        if parent is None:
            trace = Trace(trace_id=uuid.uuid4().hex)
            parent_id = None
            is_root = True
        else:
            trace = _current_trace.get()
            if trace is None:
                # Shouldn't be reachable: _current_trace is only ever unset
                # while _current_span is also unset (both are set/reset
                # together in __enter__/__exit__ for the root span). If
                # this fires, something is holding a stale SpanHandle whose
                # __exit__ already ran, or a contextvar boundary was
                # crossed unexpectedly (e.g. a bare `threading.Thread`
                # rather than a copied context).
                msg = "active span without an active trace"
                raise RuntimeError(msg)
            parent_id = parent.span_id
            is_root = False

        span = Span(
            ctx=SpanContext(trace_id=trace.trace_id, span_id=uuid.uuid4().hex, parent_id=parent_id),
            name=name,
            kind=kind,
            ts=datetime.now(UTC).isoformat(),
            start_ns=time.monotonic_ns(),
        )
        return SpanHandle(span, trace, is_root=is_root)
