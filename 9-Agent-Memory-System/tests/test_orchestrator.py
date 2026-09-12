"""Hits the real Ollama server for embeddings (via SemanticMemory) --
consistent with tests/test_semantic.py. The compress/distill LLM calls are
faked via injectable chat_fn, since testing prompt-based LLM output isn't
useful to assert on."""

import json

import pytest

from memory.compress import CompressResult, Compressor, Distiller
from memory.episodic import Episode, EpisodicMemory
from memory.orchestrator import Orchestrator
from memory.semantic import Fact, SemanticMemory
from memory.working import WorkingItem, WorkingMemory


@pytest.fixture
def stores(tmp_path):
    working = WorkingMemory(token_cap=80, snapshot_path=tmp_path / "working.json")
    episodic = EpisodicMemory(db_path=tmp_path / "episodes.db")
    semantic = SemanticMemory(qdrant_path=tmp_path / "qdrant", meta_path=tmp_path / "index_meta.json")
    yield working, episodic, semantic
    episodic.close()
    semantic.close()


class FakeCompressor:
    def compress(self, texts: list[str]) -> CompressResult:
        return CompressResult(text=" ".join(texts)[:15], reason="fake_shorten")


def _fill_working_overflow(working: WorkingMemory) -> None:
    filler = "The quick brown fox jumps over the lazy dog. " * 3
    for i in range(6):
        working.append(WorkingItem.create("assistant", f"[{i}] {filler}"))


def test_fake_compressor_shortens(stores):
    working, episodic, semantic = stores
    _fill_working_overflow(working)
    original_len = sum(len(item.text) for item in working.items())

    orch = Orchestrator(working, episodic, semantic, "s1", compressor=FakeCompressor())
    report = orch.tick()

    assert report.working_evicted > 0
    assert report.episodes_written == 1
    assert report.compress_reason_counts == {"fake_shorten": 1}
    [summary] = episodic.list("s1")
    assert summary.type == "compress_summary"
    assert len(summary.text) < original_len


def test_provider_off_still_ticks(stores):
    working, episodic, semantic = stores
    _fill_working_overflow(working)
    episodic.write(Episode.create("s1", "utterance", "seed episode so distill has something to read"))

    def _raise(*args, **kwargs):
        raise ConnectionError("ollama is down")

    orch = Orchestrator(
        working,
        episodic,
        semantic,
        "s1",
        compressor=Compressor(chat_fn=_raise),
        distiller=Distiller(chat_fn=_raise),
    )

    report = orch.tick(distill=True)  # must not raise

    assert report.compress_reason_counts.get("EXTRACTIVE_FALLBACK") == 1
    assert report.facts_distilled == 0
    assert report.facts_deduped == 0


def test_near_dup_not_inserted(stores):
    working, episodic, semantic = stores
    episodic.write(Episode.create("s1", "utterance", "conversation about favorite foods"))
    semantic.upsert_fact(Fact(text="The user's favorite fruit is mango.", namespace="s1"))

    def _fake_chat(model, prompt, format=None):
        return json.dumps({"facts": ["User's favorite fruit is mango."]})

    orch = Orchestrator(working, episodic, semantic, "s1", distiller=Distiller(chat_fn=_fake_chat))
    report = orch.tick(distill=True)

    assert report.facts_deduped == 1
    assert report.facts_distilled == 0
    assert len(semantic.search("mango", namespace="s1", k=5)) == 1
