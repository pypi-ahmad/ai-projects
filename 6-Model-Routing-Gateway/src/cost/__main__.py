"""Aggregator CLI: python -m src.cost --day today"""
from __future__ import annotations
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from .ledger import aggregate

_LOGS_DIR = Path("logs/usage")


def _load_day(day: str) -> list[dict]:
    # "today" resolves via UTC (matching ledger.log_event's file naming), not
    # local time — see the note in cost/ledger.py::log_event.
    if day == "today":
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
    path = _LOGS_DIR / f"{day}.jsonl"
    if not path.exists():
        return []  # no events yet today — not an error
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m src.cost")
    parser.add_argument("--day", default="today",
                        help="Date YYYYMMDD or 'today' (default: today)")
    args = parser.parse_args()
    events = _load_day(args.day)
    print(json.dumps(aggregate(events), indent=2))


if __name__ == "__main__":
    main()
