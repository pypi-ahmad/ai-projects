"""CLI entry point: python -m src.assembly --request FILE --policy NAME --out FILE"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

# Lets `python -m src.assembly ...` resolve `from src....` imports when invoked
# from an arbitrary cwd, without requiring the project to be pip-installed.
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.blocks.models import ContextBlock, ContextRequest
from src.budget.allocator import allocate
from src.budget.policy import load_policy
from src.assembly.packer import pack


def _block_from_dict(d: dict) -> ContextBlock:
    # Request-file schema convention: priority/compressible/droppable default the
    # same way ContextBlock itself defaults them when the key is simply absent
    # from the JSON, so a minimal fixture (id/family/text only) is still valid.
    b = ContextBlock(
        id=d["id"],
        family=d["family"],
        text=d["text"],
        priority=d.get("priority", 50),
        compressible=d.get("compressible", False),
        droppable=d.get("droppable", True),
        source=d.get("source"),
        metadata=d.get("metadata", {}),
    )
    if "created_at" in d:
        b.created_at = datetime.fromisoformat(d["created_at"])
    return b


def _request_from_dict(data: dict, policy_override: str | None) -> ContextRequest:
    return ContextRequest(
        blocks=[_block_from_dict(b) for b in data.get("blocks", [])],
        user_message=data["user_message"],
        model_name=data.get("model_name"),
        context_window=data.get("context_window"),
        reserve_output_tokens=data.get("reserve_output_tokens"),
        reserve_system_tokens=data.get("reserve_system_tokens"),
        policy=policy_override or data.get("policy", "balanced"),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Context Assembly Service — packer CLI")
    parser.add_argument("--request", required=True, help="Request JSON file")
    parser.add_argument("--policy", default=None, help="Policy name (overrides request)")
    parser.add_argument("--out", required=True, help="Output JSON file")
    parser.add_argument("--drop-note", action="store_true",
                        help="Append packing note to system message")
    args = parser.parse_args()

    data = json.loads(Path(args.request).read_text(encoding="utf-8"))
    request = _request_from_dict(data, args.policy)
    policy  = load_policy(request.policy)
    plan    = allocate(request, policy)
    result  = pack(request, plan, policy, include_drop_note=args.drop_note)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps({
            "messages":    result.messages,
            "packed_text": result.packed_text,
            "report":      result.report.as_dict(),
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    r = result.report
    print(
        f"packed  {r.token_total}/{r.context_window} tokens  "
        f"({r.leftover} leftover | {len(r.dropped)} dropped | "
        f"{len(r.compress_ids)} compress jobs)"
    )
    if r.dropped:
        for d in r.dropped:
            print(f"  dropped  {d['id']}  [{d['reason']}]")


if __name__ == "__main__":
    main()
