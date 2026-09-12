"""Dev CLI for exercising the semantic cache directly (no caller LLM):

    python -m src.cache put --query "..." --answer "..." --namespace demo
    python -m src.cache get --query "..." --namespace demo
"""

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone

from src.cache.models import CacheRecord, Hit
from src.cache.normalize import normalize_query
from src.cache.service import SemanticCache
from src.policy.enforcement import PolicyRejectedError


def _cmd_put(cache: SemanticCache, args: argparse.Namespace) -> int:
    record = CacheRecord(
        id=str(uuid.uuid4()),
        namespace=args.namespace,
        query_raw=args.query,
        query_norm=normalize_query(args.query),
        answer=args.answer,
        producer_model=args.producer_model,
        provider=args.provider,
        created_at=datetime.now(timezone.utc),
    )
    try:
        record_id = cache.put(record)
    except PolicyRejectedError as exc:
        # Exit 1 + a JSON body is the rejection contract (README.md) -- a
        # policy refusal is not the same as an uncaught exception/traceback.
        print(json.dumps({"rejected": True, "reason": exc.reason}))
        return 1
    print(json.dumps({"id": record_id}))
    return 0


def _cmd_get(cache: SemanticCache, args: argparse.Namespace) -> int:
    result = cache.get(args.query, namespace=args.namespace, producer_model=args.producer_model)
    if isinstance(result, Hit):
        output = {
            "hit": True,
            "type": result.type,
            "answer": result.answer,
            "score": result.score,
            "matched_query": result.matched_query,
        }
    else:
        output = {"hit": False, "top1_score": result.top1_score}
    print(json.dumps(output))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.cache")
    subparsers = parser.add_subparsers(dest="command", required=True)

    put_parser = subparsers.add_parser("put")
    put_parser.add_argument("--query", required=True)
    put_parser.add_argument("--answer", required=True)
    put_parser.add_argument("--namespace", default="default")
    put_parser.add_argument("--producer-model", default="manual", dest="producer_model")
    put_parser.add_argument("--provider", default="manual")

    get_parser = subparsers.add_parser("get")
    get_parser.add_argument("--query", required=True)
    get_parser.add_argument("--namespace", default="default")
    get_parser.add_argument("--producer-model", default=None, dest="producer_model")

    args = parser.parse_args(argv)
    cache = SemanticCache()

    if args.command == "put":
        return _cmd_put(cache, args)
    return _cmd_get(cache, args)


if __name__ == "__main__":
    sys.exit(main())
