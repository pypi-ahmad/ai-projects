"""CLI: uv run python -m obs.alerts.eval --once

Intentionally thin - the actual evaluation logic lives in evaluator.py so
this module (a runnable script) is never imported as a side effect of
importing the obs.alerts package.
"""

from __future__ import annotations

import argparse

from obs.alerts.evaluator import evaluate_once


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m obs.alerts.eval")
    parser.add_argument("--once", action="store_true", help="run a single evaluation pass")
    args = parser.parse_args()

    if not args.once:
        parser.print_help()
        return

    created = evaluate_once()
    if not created:
        print("No new alerts.")
        return
    for alert in created:
        print(
            f"[{alert.severity}] {alert.rule} route={alert.route} model={alert.model} "
            f"value={alert.value:.4f} threshold={alert.threshold:.4f} window={alert.window}"
        )


if __name__ == "__main__":
    main()
