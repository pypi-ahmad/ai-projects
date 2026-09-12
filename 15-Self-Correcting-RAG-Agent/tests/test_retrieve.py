"""Keyword + paraphrase retrieval tests over a small fake-wiki fixture corpus.
Skips (module-level) if Ollama isn't reachable -- these are live embed calls,
not mocked.
"""

from pathlib import Path

import ollama
import pytest

from self_correcting_rag.config import load_settings
from self_correcting_rag.index.pipeline import run_index
from self_correcting_rag.retrieve.pipeline import retrieve

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "wiki"


def _ollama_reachable() -> bool:
    try:
        ollama.Client(host=load_settings().ollama_host).list()
        return True
    except Exception:
        return False


if not _ollama_reachable():
    pytest.skip(
        "Ollama is not reachable; skipping live embed/retrieve tests", allow_module_level=True
    )


@pytest.fixture(scope="module")
def index_dir(tmp_path_factory):
    built_index_dir = tmp_path_factory.mktemp("index")
    count = run_index(FIXTURES_DIR, built_index_dir)
    assert count > 0
    return built_index_dir


def test_keyword_hit(index_dir):
    # "Quillfeather" is a distinctive proper noun that appears in exactly one
    # fixture file -- BM25 gives it the only nonzero lexical score, but RRF
    # can still tie it with a dense-only false-positive in a 9-doc corpus, so
    # assert top-3 membership rather than a fragile exact rank-1.
    results = retrieve(index_dir, "Quillfeather", k=3)
    assert results
    assert "security-incident.md" in [r.source_path for r in results]


def test_paraphrase_hit(index_dir):
    # No literal keyword overlap with pto-policy.md's wording ("unlimited
    # PTO", "Workday") -- this exercises the dense side of hybrid retrieval.
    results = retrieve(
        index_dir, "how many vacation days do employees get and who approves time off", k=3
    )
    assert results
    assert "pto-policy.md" in [r.source_path for r in results]
