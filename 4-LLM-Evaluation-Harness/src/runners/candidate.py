"""Runs a candidate model over a golden dataset file, writing one JSONL record
per case to reports/<run_id>/candidates.jsonl.

Context handling: input.context (when present) is prepended to input.user as
"Context:\\n<context>\\n\\n<user>" before the provider call -- the provider
interface itself only knows about system/user, so any case-level context is
folded into the user turn here.

Resume: a fresh --run-id is generated per invocation unless one is passed
explicitly. --resume only skips cases already present in an *existing*
reports/<run_id>/candidates.jsonl, so resuming a specific run requires
passing back the same --run-id.

skip_if: a case whose skip_if conditions aren't met by this run's provider is
never sent to the provider at all -- it gets a record with skip_reason set,
text=null, error=null, latency_ms=0.0 (downstream stages that key off
skip_reason, e.g. src.metrics and src.eval, treat it as not part of the run
rather than as an error).

Ollama VRAM: after all cases are processed, if the provider is "ollama" the
model is explicitly unloaded (keep_alive=0) so the next pipeline stage (the
judge) isn't fighting the candidate model for VRAM.
"""

import argparse
import json
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from src.dataset import Case, load_file
from src.providers import PROVIDERS
from src.providers.base import ProviderConfigError, Unloadable


def make_run_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


def load_completed_ids(candidates_path: Path) -> set[str]:
    if not candidates_path.exists():
        return set()
    ids = set()
    for line in candidates_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            ids.add(json.loads(line)["case_id"])
    return ids


def build_messages(case: Case) -> tuple[str | None, str]:
    user = case.input.user
    if case.input.context:
        user = f"Context:\n{case.input.context}\n\n{user}"
    return case.input.system, user


def skip_reason(case: Case, provider_name: str) -> str | None:
    """None if the case should run; otherwise a human-readable reason it was
    skipped for this provider, per case.skip_if.
    """
    skip_if = case.skip_if
    if skip_if is None:
        return None
    if skip_if.needs_provider and skip_if.needs_provider != provider_name:
        return f"needs_provider={skip_if.needs_provider!r}, running with {provider_name!r}"
    if skip_if.needs_ollama and provider_name != "ollama":
        return "needs_ollama=true, running with a non-Ollama provider"
    if skip_if.needs_gpu and provider_name != "ollama":
        # Ollama is the only provider in this repo that runs on a local GPU --
        # the 3 cloud providers have no GPU requirement of their own.
        return "needs_gpu=true, running with a non-Ollama (non-local-GPU) provider"
    return None


def run_candidate(
    *,
    dataset_path: Path,
    provider_name: str,
    model: str,
    out_dir: Path,
    run_id: str | None = None,
    resume: bool = False,
) -> Path:
    if provider_name not in PROVIDERS:
        raise ValueError(f"provider must be one of {tuple(PROVIDERS)}, got {provider_name!r}")
    spec = PROVIDERS[provider_name]
    if model not in spec.allowed_models:
        raise ValueError(
            f"model {model!r} is not allowed for provider {provider_name!r}; "
            f"choose one of {spec.allowed_models}"
        )

    # Raises ProviderConfigError before any case runs if a required env var is missing.
    provider = spec.factory()

    cases = load_file(dataset_path)

    run_dir = out_dir / (run_id or make_run_id())
    run_dir.mkdir(parents=True, exist_ok=True)
    candidates_path = run_dir / "candidates.jsonl"

    completed_ids = load_completed_ids(candidates_path) if resume else set()

    with candidates_path.open("a", encoding="utf-8") as fh:
        for case in cases:
            if case.id in completed_ids:
                continue

            reason = skip_reason(case, provider_name)
            if reason is not None:
                record = {
                    "case_id": case.id,
                    "text": None,
                    "model": model,
                    "provider": provider_name,
                    "latency_ms": 0.0,
                    "error": None,
                    "skip_reason": reason,
                }
                fh.write(json.dumps(record) + "\n")
                fh.flush()
                continue

            system, user = build_messages(case)
            text: str | None = None
            error: str | None = None
            start = time.monotonic()
            try:
                text = provider.complete(system=system, user=user, model=model)
            except Exception as exc:
                error = str(exc)
            latency_ms = (time.monotonic() - start) * 1000

            record = {
                "case_id": case.id,
                "text": text,
                "model": model,
                "provider": provider_name,
                "latency_ms": latency_ms,
                "error": error,
                "skip_reason": None,
            }
            fh.write(json.dumps(record) + "\n")
            fh.flush()

    if provider_name == "ollama" and isinstance(provider, Unloadable):
        provider.unload(model)

    return candidates_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.runners.candidate")
    parser.add_argument("--dataset", type=Path, required=True, help="Golden *.jsonl file")
    parser.add_argument("--provider", required=True, choices=sorted(PROVIDERS))
    parser.add_argument("--model", required=True)
    parser.add_argument("--out", type=Path, required=True, help="Reports base directory")
    parser.add_argument("--run-id", help="Reuse this run id (required to --resume a prior run)")
    parser.add_argument("--resume", action="store_true", help="Skip cases already recorded")
    args = parser.parse_args(argv)

    try:
        candidates_path = run_candidate(
            dataset_path=args.dataset,
            provider_name=args.provider,
            model=args.model,
            out_dir=args.out,
            run_id=args.run_id,
            resume=args.resume,
        )
    except (ProviderConfigError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"Wrote {candidates_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
