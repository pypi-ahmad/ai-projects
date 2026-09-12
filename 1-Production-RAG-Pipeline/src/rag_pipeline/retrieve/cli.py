"""CLI: uv run python -m rag_pipeline.retrieve --index data/indexes --query "..." --k 5"""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from rag_pipeline.retrieve.pipeline import DEFAULT_K, DEFAULT_N, run_retrieve


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rag_pipeline.retrieve")
    parser.add_argument("--index", dest="index_dir", type=Path, default=Path("data/indexes"))
    parser.add_argument("--query", required=True)
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    parser.add_argument("--n", type=int, default=DEFAULT_N)
    parser.add_argument("--hybrid", dest="hybrid", action="store_true", default=True)
    parser.add_argument("--no-hybrid", dest="hybrid", action="store_false")
    parser.add_argument("--rerank", dest="rerank", action="store_true", default=True)
    parser.add_argument("--no-rerank", dest="rerank", action="store_false")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    results = run_retrieve(
        args.index_dir, args.query, k=args.k, n=args.n, hybrid=args.hybrid, rerank=args.rerank
    )
    print(json.dumps([asdict(r) for r in results], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
