"""
Token allocation engine. No model calls.
Returns AllocationPlan: which blocks are kept, which need compression, which are dropped.
See src/assembly/packer.py to turn a plan into chat messages, or
src/compress/compressor.py to resolve plan.compress_jobs before packing.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from src.blocks.models import ContextBlock, ContextRequest
from src.blocks.tokenizer import TokenCounter
from src.budget.policy import BudgetPolicy, load_policy

# Module-level singleton — cl100k_base has no per-request state, so sharing one
# instance across all calls just avoids re-loading the tiktoken encoding.
_COUNTER = TokenCounter()
_PACKABLE = ("memory", "docs", "tools")


class DropReason(str, Enum):
    EMPTY_TEXT           = "EMPTY_TEXT"           # block.text is blank
    OVER_FAMILY_CAP      = "OVER_FAMILY_CAP"      # family cap exhausted, borrow pool also spent
    OVER_WINDOW          = "OVER_WINDOW"           # global usable window exhausted
    ZERO_PRIORITY        = "ZERO_PRIORITY"         # priority == 0 and no space
    RESERVE              = "RESERVE"               # system/user block exceeded reserve budget
    COMPRESS_UNAVAILABLE = "COMPRESS_UNAVAILABLE"  # no provider available; job skipped
    COMPRESS_FAILED      = "COMPRESS_FAILED"       # provider returned longer/equal text


@dataclass
class CompressJob:
    block: ContextBlock
    target_tokens: int              # compress block.text to fit within this many tokens
    must_keep: str | None = None    # optional comma-separated facts provider must preserve


@dataclass
class DropRecord:
    block: ContextBlock
    reason: DropReason


@dataclass
class AllocationPlan:
    kept: list[ContextBlock]
    compress_jobs: list[CompressJob]
    dropped: list[DropRecord]
    token_budget_used: int    # tokens used by kept blocks (not counting reserves)
    context_window: int
    reserve_tokens: int       # output + system + user message reserves

    @property
    def total_tokens(self) -> int:
        return self.token_budget_used + self.reserve_tokens

    @property
    def fits(self) -> bool:
        return self.total_tokens <= self.context_window


def allocate(
    request: ContextRequest,
    policy: Optional[BudgetPolicy] = None,
) -> AllocationPlan:
    """
    Allocate blocks into an AllocationPlan using three passes:
      A. Force-keep one highest-priority block per non-empty family (hard rule).
      B. Pack remaining blocks within per-family soft caps.
      C. Borrow — leftover blocks use surplus from under-used families.
    Blocks that still don't fit become compress_jobs (if compressible) or drops.
    No model is called; compress jobs are handed to src/compress/ in a later step.
    """
    if policy is None:
        policy = load_policy(request.policy)

    # Mutates request.blocks in place (sets block.token_count) — allocate() is not
    # side-effect-free with respect to the caller's own ContextBlock instances.
    _COUNTER.count_request(request)

    window   = request.resolve_window()
    out_res  = request.reserve_output_tokens if request.reserve_output_tokens is not None else policy.output_reserve(window)
    sys_res  = request.reserve_system_tokens if request.reserve_system_tokens is not None else policy.system_reserve(window)
    user_res = _COUNTER.count(request.user_message)
    total_reserve = out_res + sys_res + user_res
    usable = max(window - total_reserve, 0)

    kept:          list[ContextBlock] = []
    compress_jobs: list[CompressJob]  = []
    dropped:       list[DropRecord]   = []
    leftover:      list[ContextBlock] = []

    # Pre-filter: empty text; reserve system/user blocks (never dropped)
    pending: list[ContextBlock] = []
    for block in request.blocks:
        if not block.text.strip():
            dropped.append(DropRecord(block, DropReason.EMPTY_TEXT))
        elif block.family in ("system", "user"):
            kept.append(block)   # hard rule: never dropped
        else:
            pending.append(block)

    # Group and sort pending by family: priority desc, recency desc
    by_family: dict[str, list[ContextBlock]] = {f: [] for f in _PACKABLE}
    for b in pending:
        if b.family in by_family:
            by_family[b.family].append(b)
    # Sort within each family by priority desc; ties broken by created_at desc
    # (most recent wins). src/assembly/packer.py._sorted() uses this same key —
    # keep the two in sync or [D#]/[T#] numbering can disagree with pack order.
    for fam in _PACKABLE:
        by_family[fam].sort(key=lambda b: (b.priority, b.created_at.timestamp()), reverse=True)

    # Per-family soft caps and usage counters
    cap = {
        "memory": int(usable * policy.caps.memory),
        "docs":   int(usable * policy.caps.docs),
        "tools":  int(usable * policy.caps.tools),
    }
    fam_used: dict[str, int] = {f: 0 for f in _PACKABLE}
    total_used = 0

    # ── Pass A: force-keep one block per non-empty family ────────────────
    b_start: dict[str, int] = {}   # index where Pass B begins per family
    for fam in _PACKABLE:
        blocks = by_family[fam]
        if blocks and usable > 0:
            top = blocks[0]
            tok = top.token_count or 0
            if total_used + tok <= usable:
                kept.append(top)
                fam_used[fam] += tok
                total_used += tok
            else:
                leftover.append(top)   # even top doesn't fit; try borrow
            b_start[fam] = 1
        else:
            b_start[fam] = 0

    # ── Pass B: pack remaining within soft cap ────────────────────────────
    for fam in _PACKABLE:
        for block in by_family[fam][b_start[fam]:]:
            tok = block.token_count or 0
            if fam_used[fam] + tok <= cap[fam] and total_used + tok <= usable:
                kept.append(block)
                fam_used[fam] += tok
                total_used += tok
            else:
                leftover.append(block)

    # ── Pass C: borrow — leftover blocks consume unused family surplus ────
    leftover.sort(key=lambda b: (b.priority, b.created_at.timestamp()), reverse=True)
    for block in leftover:
        tok = block.token_count or 0
        if total_used + tok <= usable:
            kept.append(block)
            total_used += tok
        elif block.compressible and (usable - total_used) > 0:
            target = usable - total_used
            compress_jobs.append(CompressJob(block=block, target_tokens=target))
            # Pessimistically claim all remaining space for this one job: the
            # actual compressed size is unknown until src/compress/ runs, so the
            # allocator refuses to provisionally hand the same headroom to a
            # second leftover block. Net effect: at most one compress_job per
            # allocate() call — further compressible overflow is dropped, not queued.
            total_used = usable
        else:
            reason = (
                DropReason.ZERO_PRIORITY if block.priority == 0
                else DropReason.OVER_WINDOW if total_used >= usable
                else DropReason.OVER_FAMILY_CAP
            )
            dropped.append(DropRecord(block, reason))

    return AllocationPlan(
        kept=kept,
        compress_jobs=compress_jobs,
        dropped=dropped,
        token_budget_used=total_used,
        context_window=window,
        reserve_tokens=total_reserve,
    )
