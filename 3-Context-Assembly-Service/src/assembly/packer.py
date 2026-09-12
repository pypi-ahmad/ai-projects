"""
Packer: turns AllocationPlan + ContextRequest into chat messages and a BudgetReport.
No model calls. Deterministic: same inputs always produce the same output.

Message layout (always in this order):
  1. {"role": "system"} — system blocks, then memory / docs / tools sections,
                          optional packing note (off by default)
  2. {"role": "user"}   — request.user_message

See src/assembly/__main__.py for the CLI that wires allocate() + pack() together,
or src/compress/compressor.py to resolve plan.compress_jobs before calling pack().
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from src.blocks.models import ContextBlock, ContextRequest
from src.blocks.tokenizer import TokenCounter
from src.budget.allocator import AllocationPlan
from src.budget.policy import BudgetPolicy, load_policy

_COUNTER = TokenCounter()


@dataclass
class FamilyStat:
    cap: int
    used: int


@dataclass
class BudgetReport:
    context_window: int
    reserve_tokens: int
    usable: int
    per_family: dict[str, FamilyStat]       # memory / docs / tools
    kept_ids: list[str]
    dropped: list[dict[str, str]]           # [{"id": ..., "reason": ...}]
    compress_ids: list[str]
    token_total: int
    leftover: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "context_window": self.context_window,
            "reserve_tokens": self.reserve_tokens,
            "usable": self.usable,
            "per_family": {f: {"cap": s.cap, "used": s.used}
                           for f, s in self.per_family.items()},
            "kept_ids": self.kept_ids,
            "dropped": self.dropped,
            "compress_ids": self.compress_ids,
            "token_total": self.token_total,
            "leftover": self.leftover,
        }


@dataclass
class PackResult:
    messages: list[dict[str, str]]  # [{role, content}] — ready for chat API
    packed_text: str                 # flat single-string view of all context
    report: BudgetReport


def pack(
    request: ContextRequest,
    plan: AllocationPlan,
    policy: BudgetPolicy | None = None,
    include_drop_note: bool = False,
) -> PackResult:
    """Build PackResult from a pre-computed AllocationPlan. No network calls."""
    if policy is None:
        policy = load_policy(request.policy)

    def _sorted(family: str) -> list[ContextBlock]:
        return sorted(
            (b for b in plan.kept if b.family == family),
            key=lambda b: (b.priority, b.created_at.timestamp()),
            reverse=True,
        )

    sys_blocks  = _sorted("system")
    mem_blocks  = _sorted("memory")
    doc_blocks  = _sorted("docs")
    tool_blocks = _sorted("tools")

    # ── Assemble system message content (sections in document order) ──────
    parts: list[str] = []

    if sys_blocks:
        parts.append("\n\n".join(b.text for b in sys_blocks))

    if mem_blocks:
        parts.append("## Memory\n" + "\n\n".join(b.text for b in mem_blocks))

    # [D#]/[T#] tags are positional — assigned fresh from this call's sort order,
    # not derived from block.id. The same block can surface as [D1] in one pack()
    # call and [D2] in the next if the kept set changes; nothing outside this
    # function should treat these tags as stable identifiers.
    if doc_blocks:
        doc_items = [f"[D{i+1}] {b.text}" for i, b in enumerate(doc_blocks)]
        parts.append("## Retrieved Documents\n" + "\n\n".join(doc_items))

    if tool_blocks:
        tool_items = [f"[T{i+1}] {b.text}" for i, b in enumerate(tool_blocks)]
        parts.append("## Available Tools\n" + "\n\n".join(tool_items))

    if include_drop_note and plan.dropped:
        note = ", ".join(f"{r.block.id} ({r.reason.value})" for r in plan.dropped)
        parts.append(f"---\nPacking note: dropped {note}")

    system_content = "\n\n".join(parts)

    # ── Build message list ────────────────────────────────────────────────
    messages: list[dict[str, str]] = []
    if system_content.strip():
        messages.append({"role": "system", "content": system_content})
    messages.append({"role": "user", "content": request.user_message})

    packed_text = (system_content + "\n\n---\n\n" + request.user_message).strip()

    # ── Budget report ─────────────────────────────────────────────────────
    usable = plan.context_window - plan.reserve_tokens
    fam_used: dict[str, int] = {"memory": 0, "docs": 0, "tools": 0}
    for b in plan.kept:
        if b.family in fam_used:
            fam_used[b.family] += b.token_count or 0

    per_family = {
        f: FamilyStat(cap=int(usable * getattr(policy.caps, f)), used=fam_used[f])
        for f in ("memory", "docs", "tools")
    }

    report = BudgetReport(
        context_window=plan.context_window,
        reserve_tokens=plan.reserve_tokens,
        usable=usable,
        per_family=per_family,
        kept_ids=[b.id for b in plan.kept],
        dropped=[{"id": r.block.id, "reason": r.reason.value} for r in plan.dropped],
        compress_ids=[j.block.id for j in plan.compress_jobs],
        token_total=plan.total_tokens,
        leftover=usable - plan.token_budget_used,
    )

    return PackResult(messages=messages, packed_text=packed_text, report=report)
