"""Working memory: token-budgeted turn buffer, in-process + JSON snapshot.

Must not: persist automatically -- snapshot()/load() only ever run when a
caller invokes them (ui.py, scripts/seed_demo.py); must not gain a
session_id field either, this buffer is shared by the whole process (see
ui.py's module docstring for what that means for callers).

Next: src/memory/episodic.py -- what an evicted WorkingItem becomes.
"""

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import tiktoken
from pydantic import BaseModel, Field

from memory import config

Role = Literal["user", "assistant", "tool", "system"]

_ENCODER = tiktoken.get_encoding(config.TOKEN_ENCODING)


def count_tokens(text: str) -> int:
    """Deterministic token count via tiktoken (see config.TOKEN_ENCODING note)."""
    return len(_ENCODER.encode(text))


class WorkingItem(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    role: Role
    text: str
    token_count: int
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))  # always UTC; nothing in this file compares it, but see episodic.py
    pinned: bool = False
    source_id: str | None = None

    @classmethod
    def create(
        cls,
        role: Role,
        text: str,
        *,
        pinned: bool = False,
        source_id: str | None = None,
    ) -> "WorkingItem":
        """Convenience constructor: computes token_count via count_tokens(text)."""
        return cls(
            role=role,
            text=text,
            token_count=count_tokens(text),
            pinned=pinned,
            source_id=source_id,
        )


class CompressJob(BaseModel):
    """Data only -- no LLM call happens here. Phase 5's compress.py consumes these."""

    item: WorkingItem
    reason: str = "evicted_overflow"


class WorkingMemory:
    def __init__(
        self,
        token_cap: int = config.WORKING_TOKEN_CAP,
        snapshot_path: Path = config.WORKING_SNAPSHOT_PATH,
    ) -> None:
        self.token_cap = token_cap
        self._snapshot_path = snapshot_path
        self._items: list[WorkingItem] = []

    def append(self, item: WorkingItem) -> None:
        self._items.append(item)

    def items(self) -> list[WorkingItem]:
        """Items in append order (oldest first)."""
        return list(self._items)

    def total_tokens(self) -> int:
        return sum(item.token_count for item in self._items)

    def evict(self) -> list[CompressJob]:
        """Evict oldest-unpinned items while over token_cap.

        Never evicts a pinned item or the latest (most recent) user-role
        item. Each evicted item becomes a CompressJob -- eviction never
        silently drops data, it hands it off for compression.
        Stops once no evictable item remains, even if still over cap.
        """
        jobs: list[CompressJob] = []
        while self.total_tokens() > self.token_cap:
            victim = self._pick_evictable()
            if victim is None:
                break
            self._items.remove(victim)
            jobs.append(CompressJob(item=victim))
        return jobs

    def _pick_evictable(self) -> WorkingItem | None:
        latest_user_id = self._latest_user_id()
        for item in self._items:
            if item.pinned:
                continue
            if item.id == latest_user_id:
                continue
            return item
        return None

    def _latest_user_id(self) -> str | None:
        for item in reversed(self._items):
            if item.role == "user":
                return item.id
        return None

    def snapshot(self) -> None:
        self._snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        payload = [item.model_dump(mode="json") for item in self._items]
        self._snapshot_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def load(self) -> None:
        if not self._snapshot_path.exists():
            self._items = []
            return
        payload = json.loads(self._snapshot_path.read_text(encoding="utf-8"))
        self._items = [WorkingItem.model_validate(entry) for entry in payload]


def _demo() -> None:
    wm = WorkingMemory()
    print(f"token_cap={wm.token_cap}")
    filler = "The quick brown fox jumps over the lazy dog. " * 4
    all_jobs: list[CompressJob] = []
    for i in range(40):
        role: Role = "user" if i % 3 == 0 else "assistant"
        item = WorkingItem.create(role, f"[{i}] {filler}", pinned=(i == 5))
        wm.append(item)
        jobs = wm.evict()
        if jobs:
            all_jobs.extend(jobs)
            evicted = [f"{j.item.role}:{j.item.id[:8]}" for j in jobs]
            print(f"item {i}: total_tokens={wm.total_tokens()} evicted={evicted}")
    print(f"final total_tokens={wm.total_tokens()} items_remaining={len(wm.items())}")
    print(f"compress jobs produced: {len(all_jobs)}")
    for job in all_jobs:
        print(f"  job: role={job.item.role} tokens={job.item.token_count} reason={job.reason}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="fill until overflow and print jobs")
    args = parser.parse_args()
    if args.demo:
        _demo()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
