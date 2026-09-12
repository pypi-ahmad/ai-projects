"""CLI: uv run python -m rag_pipeline.chunk --in data/processed --out ...chunks.jsonl."""

import argparse
from pathlib import Path

from rag_pipeline.chunk.pipeline import (
    DEFAULT_OVERLAP_TOKENS,
    DEFAULT_TARGET_TOKENS,
    run_chunk,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rag_pipeline.chunk")
    parser.add_argument(
        "--in",
        dest="in_dir",
        type=Path,
        default=Path("data/processed"),
        help="Directory containing ingest.jsonl (from Phase 2)",
    )
    parser.add_argument("--out", type=Path, default=Path("data/processed/chunks.jsonl"))
    parser.add_argument("--target-tokens", type=int, default=DEFAULT_TARGET_TOKENS)
    parser.add_argument("--overlap-tokens", type=int, default=DEFAULT_OVERLAP_TOKENS)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    out_path = run_chunk(
        args.in_dir, args.out, target_tokens=args.target_tokens, overlap_tokens=args.overlap_tokens
    )
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
