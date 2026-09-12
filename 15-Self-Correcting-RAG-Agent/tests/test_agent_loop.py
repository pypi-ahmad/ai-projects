"""The agent loop, exercised entirely with fake rewrite/retrieve/critique/
generate functions -- no live provider, no built index. `_NullProvider` fails
loudly if the loop ever calls it directly, which it shouldn't when every
stage is faked.
"""

from pathlib import Path

from self_correcting_rag.agent.loop import run, run_safe
from self_correcting_rag.agent.schemas import CritiqueResult, LoopPolicy, RewriteResult
from self_correcting_rag.retrieve.records import RetrievalResult
from self_correcting_rag.web.base import WebResult
from self_correcting_rag.web.file_stub_search import FileStubSearch
from self_correcting_rag.web.null_search import NullSearch

UNUSED_INDEX = Path("unused")
WEB_FIXTURE = Path(__file__).parent / "fixtures" / "web.json"


class _NullProvider:
    def complete(self, *, system: str, user: str, model: str) -> str:
        raise AssertionError("provider.complete() should not be called when every stage is faked")


def _unreachable(*_args, **_kwargs):
    raise AssertionError("this stage should not run on this path")


class _UnreachableFetch:
    def fetch(self, url):
        raise AssertionError("fetch should not be called when search yields no hits")


def _fake_rewrite_factory(calls: list[list[str] | None]):
    def _fake_rewrite(provider, model, query, hints=None):
        calls.append(hints)
        return RewriteResult(queries=["rewritten query"], rationale="ok")

    return _fake_rewrite


def _fake_retrieve_one_chunk(index_dir, queries, k):
    return [RetrievalResult(chunk_id="c1", text="some text", source_path="a.md", page=1, score=1.0)]


def test_retry_path_is_taken_and_hints_flow_to_rewrite():
    critique_calls = []

    def fake_critique(provider, model, *, query, chunks, policy, iteration):
        critique_calls.append(iteration)
        if iteration == 1:
            return CritiqueResult(
                grounded=0.2, coverage=0.3, missing=["dates"], decision="retry", rationale="thin"
            )
        return CritiqueResult(
            grounded=0.9, coverage=0.9, missing=[], decision="answer", rationale="good"
        )

    rewrite_calls: list[list[str] | None] = []

    def fake_generate(provider, model, *, query, chunks, web_chunks=None):
        return "The answer is here [S1]."

    result = run(
        "original question",
        index_dir=UNUSED_INDEX,
        provider=_NullProvider(),
        policy=LoopPolicy(max_iters=2, confidence_threshold=0.6, web_enabled=False),
        rewrite_fn=_fake_rewrite_factory(rewrite_calls),
        retrieve_fn=_fake_retrieve_one_chunk,
        critique_fn=fake_critique,
        generate_fn=fake_generate,
    )

    assert critique_calls == [1, 2]
    assert rewrite_calls == [None, ["dates"]]  # 2nd rewrite got the 1st critique's missing[]
    assert result.answer == "The answer is here [S1]."
    stages = [step.stage for step in result.trace.steps]
    assert stages.count("rewrite") == 2
    assert stages.count("critique") == 2


def test_web_skipped_when_disabled():
    def fake_critique_always_web(provider, model, *, query, chunks, policy, iteration):
        return CritiqueResult(
            grounded=0.1, coverage=0.1, missing=[], decision="web", rationale="corpus weak"
        )

    spy_search_calls = []
    spy_fetch_calls = []

    class SpyWebSearch:
        def search(self, query, n):
            spy_search_calls.append(query)
            return [WebResult(url="https://example.test", title="t", snippet="s")]

    class SpyWebFetch:
        def fetch(self, url):
            spy_fetch_calls.append(url)
            return "page text"

    result = run(
        "question",
        index_dir=UNUSED_INDEX,
        provider=_NullProvider(),
        policy=LoopPolicy(max_iters=1, web_enabled=False),
        web_search=SpyWebSearch(),
        web_fetch=SpyWebFetch(),
        rewrite_fn=lambda *a, **k: RewriteResult(queries=["q"], rationale="ok"),
        retrieve_fn=lambda *a, **k: [],
        critique_fn=fake_critique_always_web,
        generate_fn=_unreachable,
    )

    assert result.answer is None
    assert "disabled" in result.reason
    assert spy_search_calls == []
    assert spy_fetch_calls == []


def test_stub_search_used_in_loop_and_web_answer_is_cited():
    """The loop's web branch, driven by FileStubSearch reading
    tests/fixtures/web.json -- exercises the requested search implementation
    end to end, not a hand-built fake.
    """

    def fake_critique_web(provider, model, *, query, chunks, policy, iteration):
        return CritiqueResult(
            grounded=0.1, coverage=0.1, missing=[], decision="web", rationale="corpus weak"
        )

    class StubFetch:
        def fetch(self, url):
            assert url == "https://example.test/self-correcting-rag"
            return "some fetched web page text"

    def fake_generate(provider, model, *, query, chunks, web_chunks=None):
        assert web_chunks and web_chunks[0].url == "https://example.test/self-correcting-rag"
        return "Per the web [W1], this is true."

    result = run(
        "question",
        index_dir=UNUSED_INDEX,
        provider=_NullProvider(),
        policy=LoopPolicy(max_iters=1, web_enabled=True),
        web_search=FileStubSearch(WEB_FIXTURE),
        web_fetch=StubFetch(),
        rewrite_fn=lambda *a, **k: RewriteResult(queries=["question"], rationale="ok"),
        retrieve_fn=lambda *a, **k: [],
        critique_fn=fake_critique_web,
        generate_fn=fake_generate,
    )

    assert result.answer == "Per the web [W1], this is true."
    assert result.citations == ["W1"]


def test_null_search_yields_no_web_chunks_and_abstains():
    def fake_critique_web(provider, model, *, query, chunks, policy, iteration):
        return CritiqueResult(
            grounded=0.1, coverage=0.1, missing=[], decision="web", rationale="corpus weak"
        )

    result = run(
        "question",
        index_dir=UNUSED_INDEX,
        provider=_NullProvider(),
        policy=LoopPolicy(max_iters=1, web_enabled=True),
        web_search=NullSearch(),
        web_fetch=_UnreachableFetch(),
        rewrite_fn=lambda *a, **k: RewriteResult(queries=["q"], rationale="ok"),
        retrieve_fn=lambda *a, **k: [],
        critique_fn=fake_critique_web,
        generate_fn=_unreachable,
    )

    assert result.answer is None
    assert "insufficient" in result.reason


def test_illegal_citation_stripped_and_confidence_lowered():
    def fake_critique_answer(provider, model, *, query, chunks, policy, iteration):
        return CritiqueResult(
            grounded=0.9, coverage=0.9, missing=[], decision="answer", rationale="good"
        )

    def fake_generate(provider, model, *, query, chunks, web_chunks=None):
        return "Approval is required [S1] and also cite [S5] for good measure."

    result = run(
        "question",
        index_dir=UNUSED_INDEX,
        provider=_NullProvider(),
        policy=LoopPolicy(max_iters=1),
        rewrite_fn=lambda *a, **k: RewriteResult(queries=["q"], rationale="ok"),
        retrieve_fn=_fake_retrieve_one_chunk,
        critique_fn=fake_critique_answer,
        generate_fn=fake_generate,
    )

    assert "[S5]" not in result.answer
    assert "[S1]" in result.answer
    assert result.citations == ["S1"]
    assert result.confidence < 0.9


def test_abstain_returns_fixed_schema_and_never_generates():
    def fake_critique_abstain(provider, model, *, query, chunks, policy, iteration):
        return CritiqueResult(
            grounded=0.1, coverage=0.1, missing=["x"], decision="abstain", rationale="no evidence"
        )

    result = run(
        "question",
        index_dir=UNUSED_INDEX,
        provider=_NullProvider(),
        policy=LoopPolicy(max_iters=1, web_enabled=False),
        rewrite_fn=lambda *a, **k: RewriteResult(queries=["q"], rationale="ok"),
        retrieve_fn=lambda *a, **k: [],
        critique_fn=fake_critique_abstain,
        generate_fn=_unreachable,
    )

    assert result.answer is None
    assert result.reason == "no evidence"
    assert result.citations == []
    assert result.trace.steps


def test_run_safe_turns_a_raising_stage_into_a_clean_abstain():
    def broken_rewrite(provider, model, query, hints=None):
        raise ValueError("simulated malformed JSON, even after repair")

    # run() itself should propagate -- proving run_safe is doing the catching.
    try:
        run(
            "question",
            index_dir=UNUSED_INDEX,
            provider=_NullProvider(),
            rewrite_fn=broken_rewrite,
            retrieve_fn=lambda *a, **k: [],
            critique_fn=_unreachable,
            generate_fn=_unreachable,
        )
        raise AssertionError("run() should have propagated the ValueError")
    except ValueError:
        pass

    result = run_safe(
        "question",
        index_dir=UNUSED_INDEX,
        provider=_NullProvider(),
        rewrite_fn=broken_rewrite,
        retrieve_fn=lambda *a, **k: [],
        critique_fn=_unreachable,
        generate_fn=_unreachable,
    )

    assert result.answer is None
    assert "simulated malformed JSON" in result.reason
    assert result.trace.steps[0].stage == "error"
