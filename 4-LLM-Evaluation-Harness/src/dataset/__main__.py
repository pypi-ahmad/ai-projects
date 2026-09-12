"""CLI entrypoint: `python -m src.dataset validate <dir>`. Thin wrapper over
loader.load_suite -- see loader.py for the actual validation logic.
"""

import argparse
import sys
from pathlib import Path

from .loader import DatasetError, load_suite


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.dataset")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser(
        "validate", help="Validate all *.jsonl cases in a directory"
    )
    validate_parser.add_argument("path", type=Path, help="Directory of golden *.jsonl files")

    args = parser.parse_args(argv)

    if args.command == "validate":
        try:
            cases = load_suite(args.path)
        except DatasetError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"OK: {len(cases)} case(s) validated in {args.path}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
