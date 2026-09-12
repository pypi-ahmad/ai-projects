import json

import ollama
import pytest

from rag_pipeline.config import load_settings
from rag_pipeline.generate.citations import extract_citations
from rag_pipeline.generate.prompt import (
    NO_CONTEXT_SYSTEM_PROMPT,
    build_context_block,
    build_system_prompt,
)
from rag_pipeline.generate.providers import agnes_provider, gemini_provider, openai_provider
from rag_pipeline.generate.providers.base import ProviderConfigError
from rag_pipeline.retrieve.records import RetrievalResult

RESULTS = [
    RetrievalResult(
        text="elephant text",
        score=0.9,
        source_path="elephant.txt",
        page=1,
        chunk_id="c1",
        fusion_rank=1,
        rerank_score=0.9,
    ),
    RetrievalResult(
        text="quantum text",
        score=0.8,
        source_path="quantum.txt",
        page=2,
        chunk_id="c2",
        fusion_rank=2,
        rerank_score=0.8,
    ),
]


def test_extract_citations_dedup_and_order() -> None:
    answer = "Elephants are big [S1]. They are also grey [S1]. Quantum computers exist [S2]."
    citations = extract_citations(answer, RESULTS)
    assert citations == [
        {"index": 1, "chunk_id": "c1", "source_path": "elephant.txt", "page": 1},
        {"index": 2, "chunk_id": "c2", "source_path": "quantum.txt", "page": 2},
    ]


def test_extract_citations_ignores_out_of_range() -> None:
    citations = extract_citations("Something happened [S1] and [S99].", RESULTS)
    assert citations == [{"index": 1, "chunk_id": "c1", "source_path": "elephant.txt", "page": 1}]


def test_extract_citations_empty_when_none_cited() -> None:
    assert extract_citations("No citations here at all.", RESULTS) == []


def test_build_context_block_tags_and_metadata() -> None:
    block = build_context_block(RESULTS)
    assert "[S1] (elephant.txt, page 1)" in block
    assert "[S2] (quantum.txt, page 2)" in block
    assert "elephant text" in block
    assert "quantum text" in block


def test_build_system_prompt_empty_results_uses_no_context_prompt() -> None:
    assert build_system_prompt([]) == NO_CONTEXT_SYSTEM_PROMPT


def test_build_system_prompt_nonempty_includes_context_and_rules() -> None:
    prompt = build_system_prompt(RESULTS)
    assert "[S1] (elephant.txt, page 1)" in prompt
    assert "Never cite a source number that is not listed" in prompt


def test_agnes_provider_missing_key_raises_clear_error() -> None:
    # AGNES_API_KEY is not set in this project's environment.
    with pytest.raises(ProviderConfigError, match="AGNES_API_KEY"):
        agnes_provider.make_provider()


def test_openai_provider_missing_keys_raises_clear_error(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    with pytest.raises(ProviderConfigError, match="OPENAI_API_KEY"):
        openai_provider.make_provider()


def test_gemini_provider_missing_key_raises_clear_error(monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(ProviderConfigError, match="GOOGLE_API_KEY"):
        gemini_provider.make_provider()


def _ollama_available() -> bool:
    try:
        ollama.Client(host=load_settings().ollama_host).list()
        return True
    except Exception:
        return False


# Every other test in this file is offline (mocked providers, pure prompt/citation
# logic). This is the one exception -- it builds a real index and calls Ollama for
# real, and skips gracefully rather than failing if Ollama isn't reachable.
@pytest.mark.skipif(not _ollama_available(), reason="Ollama is not reachable")
def test_run_generate_end_to_end_with_ollama(tmp_path) -> None:
    from rag_pipeline.generate.pipeline import run_generate
    from rag_pipeline.index.pipeline import run_index

    chunks_path = tmp_path / "chunks.jsonl"
    chunk = {
        "doc_id": "doc-a",
        "source_path": "facts.txt",
        "page": 1,
        "chunk_index": 0,
        "hash": "h1",
        "ocr_used": False,
        "text": "The city of Springvale was founded in the year 1842 by a group of "
        "settlers led by Elanor Quist.",
    }
    chunks_path.write_text(json.dumps(chunk) + "\n", encoding="utf-8")
    index_dir = tmp_path / "indexes"
    run_index(chunks_path, index_dir)

    result = run_generate(index_dir, "Who founded Springvale and when?", provider="ollama", k=1)
    assert result.model == "granite4.1:3b"
    assert result.latency_ms > 0
    assert "[S1]" in result.answer_markdown
    assert result.citations
    assert result.citations[0]["source_path"] == "facts.txt"
    assert result.retrieval_trace
    assert result.retrieval_trace[0]["chunk_id"] == result.citations[0]["chunk_id"]
