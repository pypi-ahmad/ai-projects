"""CLI: uv run python -m self_correcting_rag.eval [--qa data/eval/qa.jsonl]
[--index data/indexes] [--provider ollama]

Runs every eval case with web fallback disabled (matching what
no_web_when_disabled_rate measures) and prints the 3 headline metrics plus a
per-case summary.
"""

import argparse
from pathlib import Path

from self_correcting_rag.agent.schemas import LoopPolicy
from self_correcting_rag.eval.metrics import (
    abstain_on_unknown_rate,
    citation_legality_rate,
    no_web_when_disabled_rate,
)
from self_correcting_rag.eval.pipeline import load_cases, run_eval
from self_correcting_rag.llm.base import ProviderConfigError
from self_correcting_rag.llm.registry import PROVIDERS


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the eval set against a built index.")
    parser.add_argument("--qa", type=Path, default=Path("data/eval/qa.jsonl"))
    parser.add_argument("--index", type=Path, default=Path("data/indexes"))
    parser.add_argument("--provider", default="ollama", choices=sorted(PROVIDERS))
    args = parser.parse_args()

    spec = PROVIDERS[args.provider]
    try:
        provider = spec.factory()
    except ProviderConfigError as e:
        raise SystemExit(f"error: {e}") from e

    cases = load_cases(args.qa)
    policy = LoopPolicy(web_enabled=False)
    results = run_eval(cases, index_dir=args.index, provider=provider, policy=policy)

    for r in results:
        status = "answered" if r.answered else "abstained"
        print(
            f"[{r.case.category}] {r.case.id}: {status}"
            f" (illegal_citation={r.illegal_citation_found})"
        )

    print()
    print("citation_legality_rate:", citation_legality_rate(results))
    print("abstain_on_unknown_rate:", abstain_on_unknown_rate(results))
    print(
        "no_web_when_disabled_rate:",
        no_web_when_disabled_rate(results, web_enabled=policy.web_enabled),
    )


if __name__ == "__main__":
    main()
