"""CLI: uv run python -m rag_pipeline.generate --query "..." --provider ollama --model ..."""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from rag_pipeline.generate.pipeline import DEFAULT_K, run_generate
from rag_pipeline.generate.providers.base import ProviderConfigError
from rag_pipeline.generate.providers.registry import PROVIDERS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rag_pipeline.generate")
    parser.add_argument("--index", dest="index_dir", type=Path, default=Path("data/indexes"))
    parser.add_argument("--query", required=True)
    parser.add_argument("--provider", choices=tuple(PROVIDERS), default="ollama")
    parser.add_argument("--model", default=None, help="Defaults to the provider's default model")
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        result = run_generate(
            args.index_dir, args.query, provider=args.provider, model=args.model, k=args.k
        )
    except ProviderConfigError as exc:
        print(f"Provider configuration error: {exc}", file=sys.stderr)
        sys.exit(1)
    except (ValueError, RuntimeError) as exc:
        # RuntimeError covers other expected operational failures raised
        # deeper in the pipeline (e.g. no index_meta.json yet, or a
        # dimension mismatch on the Qdrant collection) -- same "fail
        # clearly, don't crash" contract as a missing provider key.
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    print(result.answer_markdown)
    print()
    print(json.dumps(asdict(result), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
