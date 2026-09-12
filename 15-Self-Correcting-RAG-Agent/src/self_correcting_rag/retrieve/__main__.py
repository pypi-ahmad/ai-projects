"""CLI: uv run python -m self_correcting_rag.retrieve --index data/indexes --query "..." --k 5"""

import argparse
from pathlib import Path

from self_correcting_rag.retrieve.pipeline import retrieve


def main() -> None:
    parser = argparse.ArgumentParser(description="Hybrid search over a built index.")
    parser.add_argument("--index", type=Path, default=Path("data/indexes"))
    parser.add_argument("--query", required=True)
    parser.add_argument("--k", type=int, default=5)
    args = parser.parse_args()

    for i, result in enumerate(retrieve(args.index, args.query, k=args.k), start=1):
        print(f"[{i}] score={result.score:.4f} {result.source_path}#page{result.page}")
        print(f"    {result.text[:200]}")


if __name__ == "__main__":
    main()
