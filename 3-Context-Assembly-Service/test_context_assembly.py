"""
Self-check for the legacy context_assembly.py API and providers.py helpers.
Dual-purpose: pytest collects the test_* functions normally, and running this file
directly (`python test_context_assembly.py`) re-invokes the same functions from
__main__ below for a dependency-free sanity check (see RUNBOOK.md).
"""
from context_assembly import Block, assemble, count, Decision
from providers import ollama_available_models, _best_compress_model, _OLLAMA_COMPRESS_MODELS


def test_count():
    assert count("hello world") > 0


def test_fits_all():
    blocks = [
        Block("system", "You are a helpful assistant.", family="tools", priority=100),
        Block("history", "User: hi\nAssistant: hello", family="memory", priority=80),
    ]
    r = assemble(blocks, budget=2000)
    assert "You are a helpful assistant." in r.text
    assert r.token_count <= 2000
    assert r.dropped == []
    assert len(r.kept) == 2


def test_drop_overflow():
    blocks = [
        Block("big", "word " * 500, family="docs", priority=10),
        Block("small", "keep me", family="memory", priority=100),
    ]
    r = assemble(blocks, budget=50)
    assert "keep me" in r.text
    assert any(d.name == "big" for d in r.dropped)
    assert r.token_count <= 50


def test_priority_order():
    blocks = [
        Block("low", "low priority text", family="docs", priority=1),
        Block("high", "high priority text", family="memory", priority=99),
    ]
    r = assemble(blocks, budget=2000)
    assert r.text.index("high priority") < r.text.index("low priority")


def test_utilization():
    r = assemble([Block("s", "hi", family="memory", priority=0)], budget=100)
    assert 0 < r.utilization <= 1.0


def test_decisions_recorded():
    blocks = [
        Block("big", "word " * 500, family="docs", priority=10),
        Block("small", "keep me", family="tools", priority=100),
    ]
    r = assemble(blocks, budget=50)
    assert len(r.decisions) == 2
    kept = r.kept[0]
    assert kept.name == "small"
    assert kept.tokens_used > 0
    dropped = r.dropped[0]
    assert dropped.name == "big"
    assert dropped.tokens_used == 0
    assert "overflow" in dropped.reason


def test_three_families_packed():
    blocks = [
        Block("mem1", "recent memory", family="memory", priority=90),
        Block("doc1", "reference doc", family="docs", priority=50),
        Block("tool1", "tool schema", family="tools", priority=80),
    ]
    r = assemble(blocks, budget=2000)
    assert len(r.dropped) == 0
    families = {d.family for d in r.kept}
    assert families == {"memory", "docs", "tools"}


def test_compress_skipped_when_disabled():
    # compress=True on the block but use_compress=False → should still drop
    blocks = [
        Block("big", "word " * 500, family="docs", priority=10, compress=True),
    ]
    r = assemble(blocks, budget=5, use_compress=False)
    assert any(d.name == "big" for d in r.dropped)


def test_ollama_model_preference():
    # prefer qwen3.5:2b when both are installed
    installed = ["qwen3.5:0.8b", "qwen3.5:2b"]
    assert _best_compress_model(installed) == "qwen3.5:2b"


def test_ollama_model_fallback():
    # fall back to tiny if 2b not installed
    assert _best_compress_model(["qwen3.5:0.8b"]) == "qwen3.5:0.8b"


def test_ollama_model_none():
    # returns None when nothing in the allowed list is installed
    assert _best_compress_model([]) is None
    assert _best_compress_model(["granite4.1:3b"]) is None


if __name__ == "__main__":
    test_count()
    test_fits_all()
    test_drop_overflow()
    test_priority_order()
    test_utilization()
    test_decisions_recorded()
    test_three_families_packed()
    test_compress_skipped_when_disabled()
    test_ollama_model_preference()
    test_ollama_model_fallback()
    test_ollama_model_none()
    print("All checks passed.")
