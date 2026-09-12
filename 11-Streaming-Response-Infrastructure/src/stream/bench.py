"""TTFT benchmark CLI.

    uv run python -m stream.bench --provider fake --n 20
    uv run python -m stream.bench --provider ollama --model qwen3.5:0.8b --n 5

Runs `--n` independent streams directly through `stream.session.pump` -- no
HTTP/FastAPI involved -- reads each run's real `StreamSession.metrics()
.ttft_ms`, and prints p50/p95 across the runs. `--provider fake` needs no
network; it's the fast path for exercising this tool itself.

Bypasses `stream.api`/HTTP entirely -- talks to `stream.session.pump`
directly, so it measures the adapter+session path only, not the SSE/HTTP
layer a real client experiences.
"""

import argparse
import asyncio
import math

from stream.config import BackpressureConfig
from stream.providers.fake import FakeProvider
from stream.providers.ollama import OllamaAdapter
from stream.session import StreamSession, pump

_PROMPT = [{"role": "user", "content": "Reply with exactly one short sentence."}]


def _build_provider(provider: str, model: str, *, think: bool) -> object:
    if provider == "fake":
        return FakeProvider(tokens=["The", " quick", " fox", " runs."], delay_s=0.01)
    if provider == "ollama":
        return OllamaAdapter(model, _PROMPT, think=think)
    raise SystemExit(f"unsupported --provider {provider!r} for bench (fake, ollama only)")


async def _run_once(provider: str, model: str, *, think: bool) -> float | None:
    session = StreamSession(id="bench")
    await pump(
        _build_provider(provider, model, think=think), session, BackpressureConfig(), can_pause=True
    )
    session.complete()
    return session.metrics().ttft_ms


def _percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    k = (len(ordered) - 1) * (pct / 100)
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return ordered[int(k)]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


async def _main_async(args: argparse.Namespace) -> None:
    ttfts: list[float] = []
    for i in range(args.n):
        ttft = await _run_once(args.provider, args.model, think=args.think)
        if ttft is None:
            print(f"run {i + 1}: no token received, skipped")
            continue
        ttfts.append(ttft)
        print(f"run {i + 1}: ttft={ttft:.1f}ms")

    if not ttfts:
        print("no successful runs")
        return

    print(f"\np50 TTFT: {_percentile(ttfts, 50):.1f}ms")
    print(f"p95 TTFT: {_percentile(ttfts, 95):.1f}ms")


def main() -> None:
    parser = argparse.ArgumentParser(description="Stream TTFT benchmark")
    parser.add_argument("--provider", choices=["fake", "ollama"], default="fake")
    parser.add_argument("--model", default="qwen3.5:0.8b")
    parser.add_argument("--n", type=int, default=10)
    parser.add_argument(
        "--think",
        action="store_true",
        default=False,
        help="let a reasoning-capable Ollama model think (off by default -- "
        "thinking time otherwise dominates TTFT; see stream.providers.ollama)",
    )
    asyncio.run(_main_async(parser.parse_args()))


if __name__ == "__main__":
    main()
