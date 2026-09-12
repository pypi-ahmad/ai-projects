"""CLI: uv run python -m self_correcting_rag.agent --q "..." [--index data/indexes]
[--provider ollama] [--web]

Runs the full rewrite -> retrieve -> critique -> answer/retry/web/abstain loop against a live
provider and a built index (see `python -m self_correcting_rag.index`). --web requests web
fallback, but it is force-disabled at startup unless SEARCH_API_KEY is configured (a log line
says so) -- see config.Settings.resolve_web_enabled.
"""

import argparse
import json
from pathlib import Path

from self_correcting_rag.agent.loop import run
from self_correcting_rag.agent.schemas import LoopPolicy
from self_correcting_rag.config import load_settings
from self_correcting_rag.llm.base import ProviderConfigError
from self_correcting_rag.llm.registry import PROVIDERS
from self_correcting_rag.web.base import WebSearch
from self_correcting_rag.web.http_fetch import HttpWebFetch
from self_correcting_rag.web.http_search import DEFAULT_BASE_URL, HttpSearch
from self_correcting_rag.web.null_search import NullSearch


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the self-correcting RAG agent loop.")
    parser.add_argument("--q", required=True, dest="question")
    parser.add_argument("--index", type=Path, default=Path("data/indexes"))
    parser.add_argument("--provider", default="ollama", choices=sorted(PROVIDERS))
    parser.add_argument("--max-iters", type=int, default=2)
    parser.add_argument("--confidence-threshold", type=float, default=0.6)
    parser.add_argument("--web", action="store_true", help="request web fallback if configured")
    args = parser.parse_args()

    spec = PROVIDERS[args.provider]
    try:
        provider = spec.factory()
    except ProviderConfigError as e:
        raise SystemExit(f"error: {e}") from e

    settings = load_settings()
    web_enabled = settings.resolve_web_enabled(args.web)
    web_search: WebSearch
    if web_enabled:
        assert settings.search_api_key  # guaranteed by resolve_web_enabled above
        web_search = HttpSearch(
            api_key=settings.search_api_key, base_url=settings.search_base_url or DEFAULT_BASE_URL
        )
    else:
        web_search = NullSearch()

    policy = LoopPolicy(
        confidence_threshold=args.confidence_threshold,
        max_iters=args.max_iters,
        web_enabled=web_enabled,
    )
    result = run(
        args.question,
        index_dir=args.index,
        provider=provider,
        policy=policy,
        web_search=web_search,
        web_fetch=HttpWebFetch(),
    )
    print(json.dumps(result.model_dump(), indent=2))


if __name__ == "__main__":
    main()
