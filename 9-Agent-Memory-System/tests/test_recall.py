"""recall(): working always included, token-budget enforcement,
semantic-over-episodic priority when the budget is tight, provenance shape."""

import pytest

from memory.episodic import Episode, EpisodicMemory
from memory.recall import recall
from memory.semantic import Fact, SemanticMemory
from memory.working import WorkingItem, WorkingMemory


@pytest.fixture
def stores(tmp_path):
    working = WorkingMemory(token_cap=1500, snapshot_path=tmp_path / "working.json")
    episodic = EpisodicMemory(db_path=tmp_path / "episodes.db")
    semantic = SemanticMemory(qdrant_path=tmp_path / "qdrant", meta_path=tmp_path / "index_meta.json")
    yield working, episodic, semantic
    episodic.close()
    semantic.close()


def test_working_always_included(stores):
    working, episodic, semantic = stores
    working.append(WorkingItem.create("user", "remember the launch date is March 3rd"))

    packed = recall(working, episodic, semantic, "launch date", "s1", token_budget=2000)

    assert any(p.store == "working" for p in packed.provenance)
    assert "March 3rd" in packed.text


def test_token_budget_never_exceeded(stores):
    working, episodic, semantic = stores
    for i in range(20):
        working.append(WorkingItem.create("assistant", f"filler item number {i} " * 5))
    episodic.write(Episode.create("s1", "utterance", "some episodic detail about the plan " * 5))
    semantic.upsert_fact(Fact(text="Some semantic fact about the plan.", namespace="s1"))

    packed = recall(working, episodic, semantic, "plan", "s1", token_budget=60)

    assert packed.token_count <= 60
    assert len(packed.provenance) < 22  # proves something was actually trimmed


def test_semantic_prioritized_over_episodic_when_tight(stores):
    working, episodic, semantic = stores
    episodic.write(Episode.create("s1", "utterance", "the codename is Nimbus Finch, remember it"))
    semantic.upsert_fact(Fact(text="The project codename is Nimbus Finch.", namespace="s1", confidence=0.9))

    # 15 tokens fits the 8-token fact plus a little, but not the 9-token episode too
    packed = recall(working, episodic, semantic, "codename", "s1", token_budget=15)

    included_stores = {p.store for p in packed.provenance}
    assert "semantic" in included_stores
    assert "episodic" not in included_stores


def test_provenance_has_id_store_score(stores):
    working, episodic, semantic = stores
    working.append(WorkingItem.create("user", "hi"))
    semantic.upsert_fact(Fact(text="A fact.", namespace="s1"))

    packed = recall(working, episodic, semantic, "fact", "s1", token_budget=500)

    for p in packed.provenance:
        assert p.id
        assert p.store in {"working", "episodic", "semantic"}
    semantic_entries = [p for p in packed.provenance if p.store == "semantic"]
    assert semantic_entries and all(p.score is not None for p in semantic_entries)
    working_entries = [p for p in packed.provenance if p.store == "working"]
    assert working_entries and all(p.score is None for p in working_entries)
