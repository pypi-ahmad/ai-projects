"""Evaluates a run against config/gate.yaml (and a baseline, if present), or
accepts a run as the new local baseline. Exit codes: 0 pass, 2 quality gate
fail, 3 harness/infra error (config/baseline missing or malformed, etc.) --
callers should not treat 3 as a quality regression.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import yaml
from pydantic import ValidationError

from src.eval.models import RunSummary
from src.gate.accept import DEFAULT_BASELINE_PATH, build_baseline, write_baseline
from src.gate.evaluate import evaluate_gate
from src.gate.models import Baseline, GateConfig

EXIT_PASS = 0
EXIT_GATE_FAIL = 2
EXIT_INFRA_ERROR = 3

DEFAULT_CONFIG_PATH = Path("config/gate.yaml")

_LOAD_ERRORS = (FileNotFoundError, ValidationError, json.JSONDecodeError, yaml.YAMLError)


def _load_summary(run_dir: Path) -> RunSummary:
    path = run_dir / "summary.json"
    if not path.exists():
        raise FileNotFoundError(f"no summary.json in {run_dir} -- run src.eval first")
    return RunSummary.model_validate_json(path.read_text(encoding="utf-8"))


def _run_accept(run_dir: Path, baseline_path: Path) -> int:
    if os.environ.get("CI"):
        print(
            "refusing --accept: CI env var is set -- baselines must not be accepted in CI",
            file=sys.stderr,
        )
        return EXIT_INFRA_ERROR
    try:
        baseline = build_baseline(run_dir)
    except _LOAD_ERRORS as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_INFRA_ERROR

    path = write_baseline(baseline, baseline_path)
    print(f"Accepted {run_dir} as the new baseline at {path}")
    return EXIT_PASS


def _run_evaluate(run_dir: Path, baseline_path: Path, config_path: Path) -> int:
    try:
        summary = _load_summary(run_dir)
        if not config_path.exists():
            raise FileNotFoundError(f"no gate config at {config_path}")
        config = GateConfig.model_validate(yaml.safe_load(config_path.read_text(encoding="utf-8")))
        baseline = None
        if baseline_path.exists():
            baseline = Baseline.model_validate_json(baseline_path.read_text(encoding="utf-8"))
    except _LOAD_ERRORS as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_INFRA_ERROR

    if baseline is not None and baseline.config.dataset_hash != summary.dataset_hash:
        print(
            "warning: dataset has changed since the baseline was accepted "
            f"({baseline.config.dataset_path}) -- regression-delta comparisons below may "
            "not be apples-to-apples",
            file=sys.stderr,
        )

    failures = evaluate_gate(summary, baseline, config)
    if failures:
        for failure in failures:
            print(f"FAIL [{failure.check}]: {failure.message}", file=sys.stderr)
        return EXIT_GATE_FAIL

    print(f"PASS: {run_dir} meets the gate")
    return EXIT_PASS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.gate")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run", type=Path, help="Evaluate this run directory against the gate")
    mode.add_argument("--accept", type=Path, help="Accept this run as the new local baseline")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE_PATH)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    args = parser.parse_args(argv)

    if args.accept is not None:
        return _run_accept(args.accept, args.baseline)
    return _run_evaluate(args.run, args.baseline, args.config)


if __name__ == "__main__":
    raise SystemExit(main())
