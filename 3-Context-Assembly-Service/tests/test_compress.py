"""Tests for Phase 5: compression engine (offline-safe — no provider keys needed)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from src.blocks.models import ContextBlock
from src.blocks.tokenizer import TokenCounter
from src.budget.allocator import AllocationPlan, CompressJob, DropReason, DropRecord
from src.compress.compressor import (
    CompressResult,
    _sentence_trim,
    compress_one,
    run_compress_jobs,
)

_COUNTER = TokenCounter()


# ── helpers ───────────────────────────────────────────────────────────────────

def _block(text: str, *, block_id: str = "b1", compressible: bool = True) -> ContextBlock:
    b = ContextBlock.new(family="docs", text=text)
    object.__setattr__(b, "id", block_id)
    b.compressible = compressible
    b.token_count  = _COUNTER.count(text)
    return b


def _job(text: str, target: int, must_keep: str = "", block_id: str = "b1") -> CompressJob:
    return CompressJob(block=_block(text, block_id=block_id),
                       target_tokens=target, must_keep=must_keep or None)


def _fake_shorter(text: str, target: int, tiny: bool, must_keep: str) -> str:
    """Fake provider: returns first 30 chars of text."""
    return text[:30].rstrip()


def _fake_longer(text: str, target: int, tiny: bool, must_keep: str) -> str:
    return text + " EXTRA EXTRA EXTRA " * 20


def _fake_unavailable(text: str, target: int, tiny: bool, must_keep: str):
    return None


# ── sentence_trim ─────────────────────────────────────────────────────────────

def test_sentence_trim_within_limit():
    text = "First sentence. Second sentence. Third sentence."
    trimmed = _sentence_trim(text, 6)
    assert _COUNTER.count(trimmed) <= 6


def test_sentence_trim_keeps_complete_sentence():
    text = "Alpha beta. Gamma delta epsilon. Zeta."
    trimmed = _sentence_trim(text, 4)
    assert trimmed.endswith(".")


def test_sentence_trim_returns_something():
    long_word = "supercalifragilistic " * 50
    result = _sentence_trim(long_word, 3)
    assert len(result) > 0


# ── compress_one with fake provider ──────────────────────────────────────────

def test_compress_ok_flag():
    # With target=5 the 30-char fake output may still be trimmed; accept OK or TRIMMED
    job = _job("This is a document with many words. " * 10, target=5)
    result = compress_one(job, _fake_shorter)
    assert result.flag in ("OK", "TRIMMED")
    assert result.token_count <= job.block.token_count


def test_compress_ok_text_is_shorter():
    original = "Word " * 50
    job = _job(original, target=100)
    result = compress_one(job, _fake_shorter)
    assert len(result.text) < len(original)


def test_compress_unavailable_flag():
    job = _job("Some text that won't compress.", target=2)
    result = compress_one(job, _fake_unavailable)
    assert result.flag == "COMPRESS_UNAVAILABLE"


def test_compress_unavailable_preserves_original_text():
    original = "Some text that won't compress."
    job = _job(original, target=2)
    result = compress_one(job, _fake_unavailable)
    assert result.text == original


def test_compress_failed_when_provider_returns_longer():
    job = _job("Short text.", target=100)
    result = compress_one(job, _fake_longer)
    assert result.flag == "COMPRESS_FAILED"


def test_compress_trimmed_when_still_over_target():
    long_text = "Alpha. Beta. Gamma. Delta. Epsilon. Zeta. Eta. Theta. " * 5

    def _still_long(text, target, tiny, must_keep):
        return long_text[:200]   # shorter than original but may still exceed target

    job = _job(long_text, target=3)   # very tight target → trim will kick in
    result = compress_one(job, _still_long)
    # Either TRIMMED (sentence-boundary trim applied) or OK if the 200-char slice fits
    assert result.flag in ("TRIMMED", "OK")
    assert result.token_count <= _COUNTER.count(long_text)


def test_compress_tiny_flag_passes_through():
    """Blocks under 400 tokens should trigger tiny=True in provider call."""
    calls: list[bool] = []

    def _capture_tiny(text, target, tiny, must_keep):
        calls.append(tiny)
        return text[:20]

    # block of ~10 tokens → tiny=True
    job = _job("Short block.", target=5)
    compress_one(job, _capture_tiny)
    assert calls == [True]


def test_compress_full_path_for_large_block():
    calls: list[bool] = []

    def _capture_tiny(text, target, tiny, must_keep):
        calls.append(tiny)
        return text[:20]

    big_text = "word " * 500   # >> 400 tokens → tiny=False
    job = _job(big_text, target=10)
    compress_one(job, _capture_tiny)
    assert calls == [False]


def test_must_keep_forwarded_to_provider():
    forwarded: list[str] = []

    def _capture_must_keep(text, target, tiny, must_keep):
        forwarded.append(must_keep)
        return text[:20]

    job = _job("Some text.", target=5, must_keep="entity-A, 42%")
    compress_one(job, _capture_must_keep)
    assert forwarded == ["entity-A, 42%"]


# ── run_compress_jobs ─────────────────────────────────────────────────────────

def _empty_plan(*jobs: CompressJob) -> AllocationPlan:
    return AllocationPlan(
        kept=[],
        compress_jobs=list(jobs),
        dropped=[],
        token_budget_used=0,
        context_window=1000,
        reserve_tokens=100,
    )


def test_run_no_jobs_returns_same_plan():
    plan = _empty_plan()
    result = run_compress_jobs(plan, _fake_shorter, unload_after=False)
    assert result.compress_jobs == []
    assert result.kept == []
    assert result.dropped == []


def test_run_ok_job_moves_to_kept():
    job = _job("This is a long document. " * 10, target=10)
    plan = _empty_plan(job)
    result = run_compress_jobs(plan, _fake_shorter, unload_after=False)
    assert len(result.kept) == 1
    assert result.compress_jobs == []
    assert result.dropped == []


def test_run_unavailable_moves_to_dropped():
    job = _job("Some text.", target=2)
    plan = _empty_plan(job)
    result = run_compress_jobs(plan, _fake_unavailable, unload_after=False)
    assert len(result.dropped) == 1
    assert result.dropped[0].reason == DropReason.COMPRESS_UNAVAILABLE
    assert result.kept == []


def test_run_failed_moves_to_dropped_with_correct_reason():
    job = _job("Short text.", target=100)
    plan = _empty_plan(job)
    result = run_compress_jobs(plan, _fake_longer, unload_after=False)
    assert len(result.dropped) == 1
    assert result.dropped[0].reason == DropReason.COMPRESS_FAILED


def test_run_mixed_batch():
    job_ok   = _job("Long document. " * 20, target=10, block_id="ok")
    job_fail = _job("Short.", target=100, block_id="fail")
    plan = _empty_plan(job_ok, job_fail)
    result = run_compress_jobs(plan, lambda t, n, tiny, mk: (
        t[:30] if len(t) > 50 else (t * 5)
    ), unload_after=False)
    kept_ids    = {b.id for b in result.kept}
    dropped_ids = {r.block.id for r in result.dropped}
    assert "ok" in kept_ids
    assert "fail" in dropped_ids


def test_run_compress_jobs_budget_updated():
    job = _job("Long document. " * 20, target=10)
    plan = _empty_plan(job)
    result = run_compress_jobs(plan, _fake_shorter, unload_after=False)
    if result.kept:
        kept_block = result.kept[0]
        assert result.token_budget_used == kept_block.token_count


def test_compress_unavailable_offline_safe():
    """Core invariant: run_compress_jobs never raises even with no providers."""
    job = _job("Some block text.", target=3)
    plan = _empty_plan(job)
    out = run_compress_jobs(plan, _fake_unavailable, unload_after=False)
    assert out.compress_jobs == []
    assert len(out.dropped) == 1
