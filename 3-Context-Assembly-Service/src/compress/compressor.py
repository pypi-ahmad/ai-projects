"""
Compression engine. Resolves AllocationPlan.compress_jobs into kept or dropped blocks.
No model is loaded here; all provider calls go through providers.compress().

Fallback chain (offline-safe):
  provider_fn returns None → COMPRESS_UNAVAILABLE → block dropped
  provider returns longer text → COMPRESS_FAILED → block dropped
  result still over target → hard-trim on sentence boundary → flag TRIMMED
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Callable, Literal, Optional

from src.blocks.tokenizer import TokenCounter
from src.budget.allocator import AllocationPlan, CompressJob, DropReason, DropRecord

CompressFlag = Literal["OK", "TRIMMED", "COMPRESS_FAILED", "COMPRESS_UNAVAILABLE"]

_COUNTER = TokenCounter()
_TINY_THRESHOLD = 400   # tokens; prefer smaller Ollama model below this


@dataclass
class CompressResult:
    block_id: str
    text: str
    token_count: int
    flag: CompressFlag


# ── sentence-boundary trim ────────────────────────────────────────────────────

def _sentence_trim(text: str, target_tokens: int) -> str:
    """Return the longest prefix of complete sentences that fits in target_tokens."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    buf = ""
    for sent in sentences:
        candidate = (buf + " " + sent).strip() if buf else sent
        if _COUNTER.count(candidate) <= target_tokens:
            buf = candidate
        else:
            break
    # fallback: if even one sentence is too long, hard-cut at target chars (~3 chars/token)
    return buf or text[: target_tokens * 3]


# ── default provider (wired to providers.py chain) ────────────────────────────

def _default_provider(text: str, target_tokens: int, tiny: bool,
                      must_keep: str) -> Optional[str]:
    # Imported here, not at module load: keeps providers.py's env/network reads
    # out of the import path for allocate()/pack()-only callers, so the offline
    # guarantee doesn't depend on this module being import-safe with no network.
    from providers import compress as _chain_compress
    return _chain_compress(text, target_tokens, tiny=tiny, must_keep=must_keep)


# ── single-job compression ────────────────────────────────────────────────────

def compress_one(
    job: CompressJob,
    provider_fn: Optional[Callable[[str, int, bool, str], Optional[str]]] = None,
) -> CompressResult:
    """
    Compress a single block.
    provider_fn(text, target_tokens, tiny, must_keep) -> str | None
    """
    if provider_fn is None:
        provider_fn = _default_provider

    original_tokens = job.block.token_count or _COUNTER.count(job.block.text)
    tiny = original_tokens < _TINY_THRESHOLD
    must_keep = job.must_keep or ""

    raw = provider_fn(job.block.text, job.target_tokens, tiny, must_keep)

    if raw is None:
        return CompressResult(
            block_id=job.block.id,
            text=job.block.text,
            token_count=original_tokens,
            flag="COMPRESS_UNAVAILABLE",
        )

    compressed_tokens = _COUNTER.count(raw)

    # Provider returned longer or equal text — discard, drop block
    if compressed_tokens >= original_tokens:
        return CompressResult(
            block_id=job.block.id,
            text=job.block.text,
            token_count=original_tokens,
            flag="COMPRESS_FAILED",
        )

    # Still over target — hard-trim on sentence boundary
    if compressed_tokens > job.target_tokens:
        trimmed = _sentence_trim(raw, job.target_tokens)
        return CompressResult(
            block_id=job.block.id,
            text=trimmed,
            token_count=_COUNTER.count(trimmed),
            flag="TRIMMED",
        )

    return CompressResult(
        block_id=job.block.id,
        text=raw,
        token_count=compressed_tokens,
        flag="OK",
    )


# ── batch resolution ──────────────────────────────────────────────────────────

def run_compress_jobs(
    plan: AllocationPlan,
    provider_fn: Optional[Callable[[str, int, bool, str], Optional[str]]] = None,
    unload_after: bool = True,
) -> AllocationPlan:
    """
    Resolve all compress_jobs and return a new AllocationPlan with empty compress_jobs.

    OK / TRIMMED  → block appended to kept with updated text + token_count
    COMPRESS_FAILED / COMPRESS_UNAVAILABLE → block appended to dropped
    """
    if not plan.compress_jobs:
        return plan

    new_kept    = list(plan.kept)
    new_dropped = list(plan.dropped)
    budget_used = plan.token_budget_used

    for job in plan.compress_jobs:
        result = compress_one(job, provider_fn)
        if result.flag in ("OK", "TRIMMED"):
            # Mutates the caller-owned ContextBlock in place (same pattern as
            # allocator.allocate() caching token_count) — block.text no longer
            # matches what the original caller passed in after this point.
            block = job.block
            block.text        = result.text
            block.token_count = result.token_count
            new_kept.append(block)
            budget_used += result.token_count
        else:
            reason = (
                DropReason.COMPRESS_UNAVAILABLE
                if result.flag == "COMPRESS_UNAVAILABLE"
                else DropReason.COMPRESS_FAILED
            )
            new_dropped.append(DropRecord(block=job.block, reason=reason))

    if unload_after:
        _try_unload_compress_model()

    return AllocationPlan(
        kept=new_kept,
        compress_jobs=[],
        dropped=new_dropped,
        token_budget_used=budget_used,
        context_window=plan.context_window,
        reserve_tokens=plan.reserve_tokens,
    )


def _try_unload_compress_model() -> None:
    """Best-effort: tell Ollama to release the compress model after a batch."""
    try:
        from providers import _best_compress_model, ollama_available_models, ollama_unload
        installed = ollama_available_models()
        model = _best_compress_model(installed)
        if model:
            ollama_unload(model)
    except Exception:
        pass
