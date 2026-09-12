"""Summarizes one run directory: writes summary.json and summary.md into it."""

import argparse
from pathlib import Path

from src.eval.summarize import render_markdown, summarize_run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.eval")
    parser.add_argument("--run", type=Path, required=True, help="reports/<run> directory")
    parser.add_argument("--dataset", type=Path, required=True, help="Golden *.jsonl file")
    args = parser.parse_args(argv)

    summary = summarize_run(args.run, args.dataset)

    (args.run / "summary.json").write_text(summary.model_dump_json(indent=2), encoding="utf-8")
    (args.run / "summary.md").write_text(render_markdown(summary), encoding="utf-8")

    print(f"Wrote {args.run / 'summary.json'} and {args.run / 'summary.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
