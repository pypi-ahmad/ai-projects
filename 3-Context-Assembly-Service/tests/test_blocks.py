"""Tests for src/blocks: ContextBlock/ContextRequest defaults and TokenCounter."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime
from src.blocks.models import ContextBlock, ContextRequest
from src.blocks.tokenizer import TokenCounter

_counter = TokenCounter()


def test_count_empty():
    assert _counter.count("") == 0


def test_count_deterministic():
    text = "The quick brown fox jumps over the lazy dog."
    assert _counter.count(text) == _counter.count(text)


def test_count_positive():
    assert _counter.count("hello world") > 0


def test_count_block_caches():
    block = ContextBlock.new("memory", "some cached text")
    assert block.token_count is None
    t1 = _counter.count_block(block)
    assert block.token_count == t1
    t2 = _counter.count_block(block)
    assert t1 == t2  # same object returned


def test_count_block_force_recount():
    block = ContextBlock.new("docs", "short")
    _counter.count_block(block)
    original = block.token_count
    block.text = "much longer text that should produce more tokens than the original short string"
    assert _counter.count_block(block) == original           # cache still serves old value
    assert _counter.count_block(block, force=True) > original  # force recomputes


def test_context_block_defaults():
    block = ContextBlock.new("tools", "tool schema text")
    assert block.id and len(block.id) == 32   # uuid4 hex
    assert block.droppable is True
    assert block.compressible is False
    assert block.token_count is None
    assert block.source is None
    assert block.metadata == {}
    assert isinstance(block.created_at, datetime)


def test_context_block_all_families():
    for family in ("memory", "docs", "tools", "system", "user"):
        b = ContextBlock.new(family, "x")  # type: ignore[arg-type]
        assert b.family == family


def test_resolve_window_explicit():
    req = ContextRequest(blocks=[], user_message="hi", context_window=8192)
    assert req.resolve_window() == 8192


def test_resolve_window_explicit_wins_over_model():
    # explicit context_window takes precedence even when model_name is present
    req = ContextRequest(blocks=[], user_message="hi",
                         model_name="granite4.1:3b", context_window=4096)
    assert req.resolve_window() == 4096


def test_resolve_window_granite():
    req = ContextRequest(blocks=[], user_message="hi", model_name="granite4.1:3b")
    assert req.resolve_window() == 131072  # 128 K verified


def test_resolve_window_qwen_2b():
    req = ContextRequest(blocks=[], user_message="hi", model_name="qwen3.5:2b")
    assert req.resolve_window() == 262144  # 256 K verified


def test_resolve_window_qwen_08b():
    req = ContextRequest(blocks=[], user_message="hi", model_name="qwen3.5:0.8b")
    assert req.resolve_window() == 262144


def test_resolve_window_cloud_raises():
    # Cloud models have null context_window in YAML → must raise without explicit value
    for model in ("agnes-2.5-flash", "gpt-5.6-luna", "gemini-3.5-flash-lite"):
        req = ContextRequest(blocks=[], user_message="hi", model_name=model)
        try:
            req.resolve_window()
            assert False, f"should have raised for {model}"
        except ValueError as e:
            assert "context_window" in str(e)


def test_resolve_window_unknown_raises():
    req = ContextRequest(blocks=[], user_message="hi", model_name="no-such-model")
    try:
        req.resolve_window()
        assert False, "should have raised"
    except ValueError:
        pass


def test_count_request():
    blocks = [
        ContextBlock.new("memory", "hello"),
        ContextBlock.new("docs", "world foo bar"),
    ]
    req = ContextRequest(blocks=blocks, user_message="test")
    _counter.count_request(req)
    for b in req.blocks:
        assert b.token_count is not None and b.token_count > 0


def test_count_request_skips_already_counted():
    block = ContextBlock.new("tools", "pre-counted")
    block.token_count = 999
    req = ContextRequest(blocks=[block], user_message="x")
    _counter.count_request(req)
    assert block.token_count == 999   # not overwritten


if __name__ == "__main__":
    test_count_empty()
    test_count_deterministic()
    test_count_positive()
    test_count_block_caches()
    test_count_block_force_recount()
    test_context_block_defaults()
    test_context_block_all_families()
    test_resolve_window_explicit()
    test_resolve_window_explicit_wins_over_model()
    test_resolve_window_granite()
    test_resolve_window_qwen_2b()
    test_resolve_window_qwen_08b()
    test_resolve_window_cloud_raises()
    test_resolve_window_unknown_raises()
    test_count_request()
    test_count_request_skips_already_counted()
    print("All checks passed.")
