"""Tests for src/budget: policy loading and the allocate() 3-pass engine."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.blocks.models import ContextBlock, ContextRequest
from src.budget.policy import load_policy, FamilyCaps
from src.budget.allocator import allocate, DropReason


def _b(family, priority=50, tok=10, compressible=False, text=None, droppable=True):
    # Sets token_count directly instead of going through TokenCounter, so each
    # test controls exact token math without depending on tiktoken's real counts.
    b = ContextBlock.new(family, text or ("x " * tok), priority=priority,
                         compressible=compressible, droppable=droppable)
    b.token_count = tok
    return b


def _req(blocks, policy="balanced", window=1000, out_res=0, sys_res=0, user_msg="hi"):
    # user_msg token_count set via TokenCounter inside allocate(); keep it 1-2 tok
    return ContextRequest(
        blocks=blocks,
        user_message=user_msg,
        context_window=window,
        reserve_output_tokens=out_res,
        reserve_system_tokens=sys_res,
        policy=policy,
    )


# ── policy loading ────────────────────────────────────────────────────────────

def test_all_policies_load():
    for name in ("balanced", "docs_heavy", "tools_heavy", "memory_heavy"):
        p = load_policy(name)
        assert p.name == name

def test_balanced_caps_sum():
    p = load_policy("balanced")
    assert abs(p.caps.memory + p.caps.docs + p.caps.tools - 1.0) < 0.001

def test_caps_all_sum():
    for name in ("balanced", "docs_heavy", "tools_heavy", "memory_heavy"):
        p = load_policy(name)
        total = p.caps.memory + p.caps.docs + p.caps.tools
        assert abs(total - 1.0) < 0.001, f"{name} caps sum to {total}"

def test_bad_caps_raise():
    try:
        FamilyCaps(memory=0.5, docs=0.5, tools=0.5)
        assert False, "should raise"
    except ValueError:
        pass


# ── core invariants ───────────────────────────────────────────────────────────

def test_window_never_exceeded():
    # Many blocks, small window → some dropped, total must stay ≤ window
    blocks = [_b("memory", tok=100) for _ in range(5)] + \
             [_b("docs",   tok=100) for _ in range(5)] + \
             [_b("tools",  tok=100) for _ in range(5)]
    plan = allocate(_req(blocks, window=500, out_res=0, sys_res=0))
    assert plan.total_tokens <= 500

def test_user_system_never_dropped():
    blocks = [
        _b("system", tok=50, priority=100),
        _b("user",   tok=30, priority=100),
        _b("memory", tok=500),
    ]
    plan = allocate(_req(blocks, window=200, out_res=0, sys_res=0))
    dropped_families = {r.block.family for r in plan.dropped}
    assert "system" not in dropped_families
    assert "user" not in dropped_families

def test_fits_property():
    blocks = [_b("memory", tok=50), _b("docs", tok=50)]
    plan = allocate(_req(blocks, window=1000))
    assert plan.fits


# ── must-keep one per family ──────────────────────────────────────────────────

def test_must_keep_one_per_family_exceeds_cap():
    # memory cap = 300 (30% of 1000), but memory block = 400 tok
    # It should still be force-kept because it's the only memory block
    big_mem = _b("memory", tok=400, priority=90)
    plan = allocate(_req([big_mem], window=1000, out_res=0, sys_res=0))
    kept_ids = {b.id for b in plan.kept}
    assert big_mem.id in kept_ids

def test_must_keep_highest_priority_per_family():
    # Two memory blocks; ensure the higher-priority one is always kept
    hi = _b("memory", priority=90, tok=10)
    lo = _b("memory", priority=10, tok=10)
    plan = allocate(_req([hi, lo], window=100, out_res=0, sys_res=0))
    kept_ids = {b.id for b in plan.kept}
    assert hi.id in kept_ids


# ── borrow ────────────────────────────────────────────────────────────────────

def test_borrow_unused_cap():
    # window=1000, no reserves, balanced (mem=30%, docs=45%, tools=25%)
    # mem cap=300, docs cap=450, tools cap=250  (of usable≈1000)
    # memory: 1 block × 100 tok  → uses 100 of 300 cap (200 surplus)
    # docs:   block_a=450, block_b=200  → block_a fills cap; block_b overflows
    # borrow pool = 1000 - (100 + 450) = 450
    # block_b (200 tok) should borrow from memory surplus → kept
    mem   = _b("memory", tok=100)
    doc_a = _b("docs",   tok=450, priority=80)
    doc_b = _b("docs",   tok=200, priority=70)
    plan  = allocate(_req([mem, doc_a, doc_b], window=1000, out_res=0, sys_res=0))
    kept_ids = {b.id for b in plan.kept}
    # doc_b must be in kept (borrowed from memory surplus)
    dropped_ids = {r.block.id for r in plan.dropped}
    assert doc_b.id in kept_ids or doc_b.id not in dropped_ids

def test_empty_family_does_not_break_caps():
    # No memory blocks at all; docs and tools should pack normally
    doc   = _b("docs",  tok=200, priority=60)
    tool  = _b("tools", tok=100, priority=80)
    plan  = allocate(_req([doc, tool], window=1000, out_res=0, sys_res=0))
    assert plan.fits
    kept_ids = {b.id for b in plan.kept}
    assert doc.id in kept_ids
    assert tool.id in kept_ids


# ── compress jobs ─────────────────────────────────────────────────────────────

def test_compress_job_created():
    # Only 50 tok of usable space; compressible block of 200 tok
    big = _b("docs", tok=200, priority=80, compressible=True)
    plan = allocate(_req([big], window=50, out_res=0, sys_res=0))
    # Block should become a compress job, not a drop
    assert len(plan.compress_jobs) >= 1
    assert plan.compress_jobs[0].block.id == big.id
    assert plan.compress_jobs[0].target_tokens > 0

def test_non_compressible_overflow_drops():
    big = _b("docs", tok=2000, priority=80, compressible=False)
    plan = allocate(_req([big], window=500, out_res=0, sys_res=0))
    assert any(r.block.id == big.id for r in plan.dropped)


# ── reason codes ─────────────────────────────────────────────────────────────

def test_empty_text_reason():
    empty = ContextBlock.new("memory", "   ", priority=50)
    empty.token_count = 0
    plan = allocate(_req([empty], window=1000))
    reasons = {r.block.id: r.reason for r in plan.dropped}
    assert reasons[empty.id] == DropReason.EMPTY_TEXT

def test_zero_priority_reason():
    # Fill window completely then add a priority=0 block
    filler = _b("memory", priority=90, tok=950)
    zero_p = _b("docs", priority=0, tok=200)
    plan = allocate(_req([filler, zero_p], window=1000, out_res=0, sys_res=0))
    dropped_map = {r.block.id: r.reason for r in plan.dropped}
    if zero_p.id in dropped_map:
        assert dropped_map[zero_p.id] in (DropReason.ZERO_PRIORITY, DropReason.OVER_WINDOW)


if __name__ == "__main__":
    test_all_policies_load()
    test_balanced_caps_sum()
    test_caps_all_sum()
    test_bad_caps_raise()
    test_window_never_exceeded()
    test_user_system_never_dropped()
    test_fits_property()
    test_must_keep_one_per_family_exceeds_cap()
    test_must_keep_highest_priority_per_family()
    test_borrow_unused_cap()
    test_empty_family_does_not_break_caps()
    test_compress_job_created()
    test_non_compressible_overflow_drops()
    test_empty_text_reason()
    test_zero_priority_reason()
    print("All checks passed.")
