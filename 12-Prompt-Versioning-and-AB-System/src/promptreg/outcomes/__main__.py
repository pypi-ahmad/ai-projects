"""CLI: per-arm outcome summary for one experiment.

uv run python -m promptreg.outcomes summary --experiment 1
"""

from __future__ import annotations

import argparse
import json
import os

from promptreg.outcomes.storage import OutcomeStore

DB_PATH = os.environ.get("PROMPTREG_DB_PATH", "data/registry.db")
OUTCOMES_JSONL = os.environ.get("PROMPTREG_OUTCOMES_JSONL", "data/outcomes.jsonl")


def _summary(args: argparse.Namespace) -> None:
    outcomes = OutcomeStore(DB_PATH, OUTCOMES_JSONL)
    print(json.dumps(outcomes.summary(args.experiment), indent=2))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m promptreg.outcomes")
    sub = parser.add_subparsers(required=True)

    summary_cmd = sub.add_parser("summary", help="per-arm outcome counts for one experiment")
    summary_cmd.add_argument("--experiment", required=True, type=int)
    summary_cmd.set_defaults(func=_summary)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
