"""CLI: uv run python -m obs.export --day today --summary

Not imported by obs/export/__init__.py, so `python -m obs.export` doesn't
hit the double-import gotcha documented in alerts/eval.py and api/__init__.py
- __main__.py is special-cased by Python's own `-m` handling.
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from obs.export.sqlite import DEFAULT_DB_PATH

if TYPE_CHECKING:
    from pathlib import Path


def _resolve_day(day: str) -> str:
    # "today" is UTC today, matching the UTC ts every span is stamped with -
    # not the machine's local date.
    if day == "today":
        return datetime.now(UTC).strftime("%Y-%m-%d")
    digits = day.replace("-", "")
    return f"{digits[0:4]}-{digits[4:6]}-{digits[6:8]}"


def print_summary(day: str, *, db_path: Path = DEFAULT_DB_PATH) -> None:
    if not db_path.exists():
        print(f"No data at {db_path}")
        return

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        like = f"{day}%"
        spans = conn.execute("SELECT * FROM spans WHERE ts LIKE ?", (like,)).fetchall()
        if not spans:
            print(f"No spans for {day}")
            return

        trace_ids = {s["trace_id"] for s in spans}
        status_counts: dict[str, int] = {}
        model_counts: dict[str, int] = {}
        for s in spans:
            status_counts[s["status"]] = status_counts.get(s["status"], 0) + 1
            if s["model"]:
                model_counts[s["model"]] = model_counts.get(s["model"], 0) + 1

        usage_rows = conn.execute(
            "SELECT u.* FROM usage u JOIN spans s ON u.span_id = s.span_id WHERE s.ts LIKE ?",
            (like,),
        ).fetchall()
        total_cost = sum(u["cost_est"] for u in usage_rows if u["cost_est"] is not None)
        unpriced = sum(1 for u in usage_rows if u["pricing"] == "UNPRICED")
    finally:
        conn.close()

    print(f"Summary for {day}")
    print(f"  traces: {len(trace_ids)}")
    print(f"  spans:  {len(spans)}")
    print(f"  status: {dict(status_counts)}")
    print(f"  models: {dict(model_counts)}")
    print(f"  cost_est total: {total_cost:.6f} USD")
    print(f"  unpriced usage rows: {unpriced}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m obs.export")
    parser.add_argument("--day", default="today", help="YYYYMMDD, YYYY-MM-DD, or 'today' (UTC)")
    parser.add_argument("--summary", action="store_true", help="print a summary for --day")
    args = parser.parse_args()

    if not args.summary:
        parser.print_help()
        return

    print_summary(_resolve_day(args.day))


if __name__ == "__main__":
    main()
