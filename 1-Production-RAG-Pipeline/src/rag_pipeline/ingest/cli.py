"""CLI entry point: uv run python -m rag_pipeline.ingest --input data/raw --out data/processed"""

import argparse
import logging
from pathlib import Path

from rag_pipeline.ingest.pipeline import run_ingest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rag_pipeline.ingest")
    parser.add_argument("--input", type=Path, default=Path("data/raw"))
    parser.add_argument("--out", type=Path, default=Path("data/processed"))
    parser.add_argument(
        "--translate",
        action="store_true",
        help="Translate pages whose language differs from --target-lang, via translategemma:4b",
    )
    parser.add_argument("--target-lang", default="en", help="Target language code (default: en)")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
    out_path = run_ingest(
        args.input, args.out, translate=args.translate, target_lang=args.target_lang
    )
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
