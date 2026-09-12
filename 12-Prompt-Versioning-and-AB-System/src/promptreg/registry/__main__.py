"""CLI: resolve a prompt name for a user, run it (dry unless a completer is
registered), and record the outcome event.

    uv run python -m promptreg.registry resolve --name support --user u1
"""

from __future__ import annotations

import argparse
import os
import sys

from promptreg.execute.completer import execute
from promptreg.outcomes.storage import OutcomeStore
from promptreg.registry.storage import IntegrityError, Registry
from promptreg.split.storage import ExperimentStore

DB_PATH = os.environ.get("PROMPTREG_DB_PATH", "data/registry.db")
PROMPTS_DIR = os.environ.get("PROMPTREG_PROMPTS_DIR", "data/prompts")
OUTCOMES_JSONL = os.environ.get("PROMPTREG_OUTCOMES_JSONL", "data/outcomes.jsonl")


def _resolve(args: argparse.Namespace) -> None:
    registry = Registry(DB_PATH, PROMPTS_DIR)
    experiments = ExperimentStore(DB_PATH)
    outcomes = OutcomeStore(DB_PATH, OUTCOMES_JSONL)

    resolution = experiments.resolve(registry, args.name, args.user, args.env)
    try:
        version = registry.get(args.name, resolution.version)
    except IntegrityError as exc:
        print(f"INTEGRITY error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    if version.body is None:  # narrows str | None -- Registry.get always populates it
        msg = f"version body missing for {args.name!r} v{resolution.version}"
        raise RuntimeError(msg)
    result = execute(version.body, version.config)
    event = outcomes.record(
        args.user,
        args.name,
        resolution.version,
        resolution.arm,
        resolution.experiment_id,
        result,
    )

    print(f"request_id: {event.request_id}")
    print(f"version: {resolution.version}  arm: {resolution.arm}  reason: {resolution.reason}")
    print(f"dry: {result.dry}  ok: {result.ok}  latency_ms: {result.latency_ms:.2f}")
    print("---")
    print(version.body)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m promptreg.registry")
    sub = parser.add_subparsers(required=True)

    resolve_cmd = sub.add_parser(
        "resolve", help="resolve a prompt for a user and run it (dry by default)"
    )
    resolve_cmd.add_argument("--name", required=True)
    resolve_cmd.add_argument("--user", required=True)
    resolve_cmd.add_argument("--env", default="prod", choices=["prod", "staging"])
    resolve_cmd.set_defaults(func=_resolve)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
