"""CLI: report per-namespace hit rate over a trailing window.

    python -m src.metrics --hours 24
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone

from src.metrics.aggregator import aggregate, read_events


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.metrics")
    parser.add_argument(
        "--hours", type=float, default=24.0, help="Look back this many hours (default 24)"
    )
    args = parser.parse_args(argv)

    since = datetime.now(timezone.utc) - timedelta(hours=args.hours)
    stats = aggregate(read_events(since=since))

    output = {namespace: s.model_dump() for namespace, s in sorted(stats.items())}
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
