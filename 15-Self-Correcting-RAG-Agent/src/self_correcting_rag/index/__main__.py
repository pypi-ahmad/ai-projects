"""CLI: uv run python -m self_correcting_rag.index --input data/raw --index data/indexes"""

import argparse
from pathlib import Path

from self_correcting_rag.index.pipeline import run_index


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest, chunk, embed, and index a corpus.")
    parser.add_argument("--input", type=Path, default=Path("data/raw"))
    parser.add_argument("--index", type=Path, default=Path("data/indexes"))
    parser.add_argument(
        "--ocr", action="store_true", help="note scanned pages explicitly (not yet implemented)"
    )
    args = parser.parse_args()

    args.index.mkdir(parents=True, exist_ok=True)
    count = run_index(args.input, args.index, ocr=args.ocr)
    print(f"Indexed {count} chunk(s) from {args.input} into {args.index}")


if __name__ == "__main__":
    main()
