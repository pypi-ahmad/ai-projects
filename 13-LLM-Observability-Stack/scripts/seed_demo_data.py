"""Seed 30 synthetic traces (some errors, some slow) via the real Tracer +
exporters, so the UI has something to show.

uv run python scripts/seed_demo_data.py
"""

from __future__ import annotations

import random
import time

from obs.export import register_default_exporters
from obs.trace import Tracer

ROUTES = ["/chat", "/summarize", "/search"]
MODELS = ["qwen3.5:0.8b", "qwen3.5:2b", "granite4.1:3b"]
TRACE_COUNT = 30

# Fixed seed: reruns produce the same mix of routes/models/errors, so a
# demo doesn't accidentally look different run to run.
random.seed(7)


def _one_trace(i: int) -> None:
    route = random.choice(ROUTES)
    model = random.choice(MODELS)
    is_error = i % 7 == 0
    is_slow = i % 6 == 0

    try:
        with Tracer.start("request") as root:
            root.set_trace(route=route)
            with root.child("generate") as gen:
                gen.set(provider="ollama", model=model)
                gen.set_prompt(f"Synthetic demo prompt #{i}")
                # Real sleep, not a faked latency_ms: latency is computed
                # from actual elapsed time in tracer.py's __exit__, so this
                # is the only way to make some spans record as genuinely
                # slower than others.
                time.sleep(random.uniform(1.0, 1.8) if is_slow else random.uniform(0.01, 0.15))
                gen.set_usage(
                    in_tokens=random.randint(20, 400),
                    out_tokens=random.randint(10, 300),
                    ttft_ms=random.uniform(50, 900),
                )
                if is_error:
                    msg = "synthetic demo failure"
                    raise RuntimeError(msg)
    except RuntimeError:
        pass  # status=error is already recorded on both spans; just move on


def main() -> None:
    register_default_exporters()
    for i in range(TRACE_COUNT):
        _one_trace(i)
    print(f"Seeded {TRACE_COUNT} traces into data/obs.db and data/traces/.")


if __name__ == "__main__":
    main()
