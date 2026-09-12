"""Hits the real Ollama server (qwen3-embedding:0.6b must be pulled and
`ollama serve` running) -- embedding quality is the thing under test."""

import pytest

from memory.semantic import Fact, RebuildRequiredError, SemanticMemory


@pytest.fixture
def store(tmp_path):
    mem = SemanticMemory(qdrant_path=tmp_path / "qdrant", meta_path=tmp_path / "index_meta.json")
    yield mem
    mem.close()


def test_paraphrase_retrieves_fact(store):
    fact = Fact(text="The user's favorite color is teal.", namespace="global")
    store.upsert_fact(fact)

    matches = store.search("what color does the user like best?", namespace="global", k=3)

    assert any(m.fact.id == fact.id for m in matches)


def test_other_namespace_does_not_see_it(store):
    fact = Fact(text="This session's private detail is a secret passphrase.", namespace="session-a")
    store.upsert_fact(fact)

    matches = store.search("secret passphrase", namespace="session-b", k=3)

    assert matches == []


def test_invalidate_sets_timestamp(store):
    fact = Fact(text="Something that will later be invalidated.", namespace="global")
    store.upsert_fact(fact)

    store.invalidate(fact.id)

    matches = store.search("something invalidated", namespace="global", k=3)
    match = next(m for m in matches if m.fact.id == fact.id)
    assert match.fact.invalidated_at is not None


def test_rebuild_required_on_model_mismatch(tmp_path):
    meta_path = tmp_path / "index_meta.json"
    meta_path.write_text('{"embed_model": "some-other-model", "dim": 999}', encoding="utf-8")

    with pytest.raises(RebuildRequiredError):
        SemanticMemory(qdrant_path=tmp_path / "qdrant", meta_path=meta_path)
