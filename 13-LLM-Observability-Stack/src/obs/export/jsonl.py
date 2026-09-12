"""Append-only JSONL export: one line per span, one file per UTC day.

Write-only, no reader (JSONL isn't queried by this codebase - SQLite is;
see export/query.py). Must not compute pricing itself - delegates to
export/common.py's span_row/priced_usage so both exporters agree. Next
file to read: sqlite.py (the other exporter, same Trace -> rows shape).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from obs.export.common import span_row

if TYPE_CHECKING:
    from obs.trace.models import Trace

DEFAULT_BASE_DIR = Path("data/traces")


class JsonlExporter:
    """Callable exporter: register with obs.trace.register_exporter."""

    def __init__(self, base_dir: Path = DEFAULT_BASE_DIR) -> None:
        self.base_dir = base_dir

    def __call__(self, trace: Trace) -> None:
        # Rotated per span's own ts (UTC date), not per trace: a trace that
        # straddles midnight can spread its spans across two files. That's
        # accepted as a rare edge case rather than special-cased.
        for span in trace.spans:
            day = span.ts[:10].replace("-", "")
            self.base_dir.mkdir(parents=True, exist_ok=True)
            path = self.base_dir / f"{day}.jsonl"
            row = span_row(trace.trace_id, span)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
