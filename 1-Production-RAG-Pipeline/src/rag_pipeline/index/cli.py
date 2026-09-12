"""CLI: uv run python -m rag_pipeline.index --chunks data/processed/chunks.jsonl --index ..."""

import argparse
import logging
from pathlib import Path

from rag_pipeline.index.pipeline import DEFAULT_EMBED_MODEL, EMBED_MODELS, run_index


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rag_pipeline.index")
    parser.add_argument("--chunks", type=Path, default=Path("data/processed/chunks.jsonl"))
    parser.add_argument("--index", dest="index_dir", type=Path, default=Path("data/indexes"))
    parser.add_argument("--embed-model", choices=EMBED_MODELS, default=DEFAULT_EMBED_MODEL)
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
    report = run_index(args.chunks, args.index_dir, embed_model=args.embed_model)
    print(
        f"Indexed {report.chunk_count} chunks "
        f"({report.embedded_count} embedded, {report.skipped_count} unchanged) "
        f"-> {report.index_path}"
    )


if __name__ == "__main__":
    main()
