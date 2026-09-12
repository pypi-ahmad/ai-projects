"""Compressor/Distiller: extractive fallback, JSON repair, and their
failure paths. No Ollama needed -- chat_fn is faked throughout."""

import json

import pytest
from pydantic import ValidationError

from memory.compress import CompressResult, Compressor, Distiller, DistillResult
from memory.episodic import Episode


def test_compressor_falls_back_when_provider_down():
    def _raise(model, prompt, format=None):
        raise ConnectionError("down")

    result = Compressor(chat_fn=_raise).compress(["First sentence here. Second one. Last sentence."])

    assert result.reason == "EXTRACTIVE_FALLBACK"
    assert result.text  # non-empty


def test_compressor_uses_llm_output_when_available():
    def _fake(model, prompt, format=None):
        return "  a tidy summary  "

    result = Compressor(chat_fn=_fake).compress(["irrelevant"])

    assert result == CompressResult(text="a tidy summary", reason="llm_summary")


def test_distiller_repairs_invalid_json_once():
    calls = []

    def _fake(model, prompt, format=None):
        calls.append(model)
        if len(calls) == 1:
            return "not json at all"
        return json.dumps({"facts": ["repaired fact"]})

    episodes = [Episode.create("s1", "utterance", "hello")]
    result = Distiller(model="qwen3.5:2b", chat_fn=_fake).distill(episodes)

    assert result.facts == ["repaired fact"]
    assert len(calls) == 2
    assert calls[1] == "qwen3.5:0.8b"  # repair always uses the default model


def test_distiller_gives_up_after_failed_repair():
    def _always_broken(model, prompt, format=None):
        return "still not json"

    episodes = [Episode.create("s1", "utterance", "hello")]
    result = Distiller(chat_fn=_always_broken).distill(episodes)

    assert result.facts == []


def test_distiller_empty_episode_list_is_a_noop():
    calls = []

    def _fake(model, prompt, format=None):
        calls.append(1)
        return json.dumps({"facts": []})

    result = Distiller(chat_fn=_fake).distill([])

    assert result.facts == []
    assert calls == []  # never even calls the model


def test_distill_result_rejects_more_than_five_facts():
    with pytest.raises(ValidationError):
        DistillResult(facts=[f"fact {i}" for i in range(6)])
