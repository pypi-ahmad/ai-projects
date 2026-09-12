"""CLI: uv run python -m rag_pipeline.eval --index data/indexes --qa data/eval/qa.jsonl"""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from rag_pipeline.eval.pipeline import run_eval
from rag_pipeline.generate.pipeline import DEFAULT_K
from rag_pipeline.generate.providers.registry import PROVIDERS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rag_pipeline.eval")
    parser.add_argument("--index", dest="index_dir", type=Path, default=Path("data/indexes"))
    parser.add_argument("--qa", dest="qa_path", type=Path, default=Path("data/eval/qa.jsonl"))
    parser.add_argument("--provider", choices=tuple(PROVIDERS), default="ollama")
    parser.add_argument("--model", default=None)
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    parser.add_argument(
        "--judge-model",
        default=None,
        help="Enable faithfulness scoring via this Ollama model (e.g. qwen3.5:2b). Off by default.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    report = run_eval(
        args.index_dir,
        args.qa_path,
        provider=args.provider,
        model=args.model,
        k=args.k,
        judge_model=args.judge_model,
    )
    print(f"Cases: {len(report.cases)}")
    print(f"recall@{report.k}: {report.mean_recall_at_k}")
    print(f"citation hit rate: {report.mean_citation_hit_rate}")
    print(f"mean latency (ms): {report.mean_latency_ms:.1f}")
    if report.judge_model:
        print(f"faithfulness ({report.judge_model}): {report.mean_faithfulness}")
    print(json.dumps([asdict(c) for c in report.cases], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
