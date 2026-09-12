"""WorkingMemory: cap enforcement, pinned/latest-user protection, snapshot round-trip."""

from memory.working import WorkingItem, WorkingMemory, count_tokens


def _item(role: str, tokens: int, pinned: bool = False) -> WorkingItem:
    return WorkingItem(role=role, text=f"item-{tokens}", token_count=tokens, pinned=pinned)


def test_cap_honored():
    wm = WorkingMemory(token_cap=100)
    for _ in range(10):
        wm.append(_item("assistant", 30))

    jobs = wm.evict()

    assert wm.total_tokens() <= 100
    assert len(jobs) > 0


def test_pinned_survives():
    wm = WorkingMemory(token_cap=50)
    pinned = _item("assistant", 40, pinned=True)
    wm.append(pinned)
    for _ in range(5):
        wm.append(_item("assistant", 30))

    wm.evict()

    assert pinned.id in {item.id for item in wm.items()}


def test_latest_user_survives():
    wm = WorkingMemory(token_cap=50)
    user_item = _item("user", 40)
    wm.append(user_item)
    for _ in range(5):
        wm.append(_item("assistant", 30))

    wm.evict()

    assert user_item.id in {item.id for item in wm.items()}


def test_count_tokens_deterministic():
    assert count_tokens("") == 0
    assert count_tokens("hello world") == count_tokens("hello world")
    assert count_tokens("hello world") > 0


def test_snapshot_roundtrip(tmp_path):
    path = tmp_path / "working.json"
    wm = WorkingMemory(token_cap=1500, snapshot_path=path)
    wm.append(WorkingItem.create("user", "hi there", pinned=True))
    wm.append(WorkingItem.create("assistant", "hello!"))
    wm.snapshot()

    reloaded = WorkingMemory(token_cap=1500, snapshot_path=path)
    reloaded.load()

    assert [item.text for item in reloaded.items()] == [item.text for item in wm.items()]
    assert reloaded.items()[0].pinned is True
