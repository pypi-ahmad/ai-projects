"""The self-correction loop: rewrite -> retrieve -> critique -> answer | retry
| web | abstain. See docs/ARCHITECTURE.md for the diagram this implements.

Every stage is an injectable callable (defaulting to the real implementation)
so callers -- tests especially -- can swap in fakes without a live provider
or a built index.
"""

from collections.abc import Callable
from pathlib import Path

from self_correcting_rag.agent.citations import check_citations
from self_correcting_rag.agent.critique import DEFAULT_CRITIQUE_MODEL, critique
from self_correcting_rag.agent.generate import DEFAULT_ANSWER_MODEL, generate
from self_correcting_rag.agent.rewrite import DEFAULT_REWRITE_MODEL, rewrite
from self_correcting_rag.agent.schemas import (
    AgentResult,
    AgentTrace,
    CritiqueResult,
    LoopPolicy,
    RewriteResult,
)
from self_correcting_rag.llm.base import Provider
from self_correcting_rag.retrieve.pipeline import retrieve_multi
from self_correcting_rag.retrieve.records import RetrievalResult
from self_correcting_rag.web.base import WebFetch, WebSearch
from self_correcting_rag.web.fetch import fetch_web_chunks
from self_correcting_rag.web.records import WebChunk

RETRIEVE_K = 5
# ponytail: a flat penalty, not a re-critique of the cleaned answer -- upgrade
# to scoring the stripped text if a flat penalty proves too coarse in practice.
ILLEGAL_CITATION_PENALTY = 0.2

RewriteFn = Callable[[Provider, str, str, list[str] | None], RewriteResult]
RetrieveFn = Callable[[Path, list[str], int], list[RetrievalResult]]
CritiqueFn = Callable[..., CritiqueResult]
GenerateFn = Callable[..., str]


def run(
    question: str,
    *,
    index_dir: Path,
    provider: Provider,
    rewrite_model: str = DEFAULT_REWRITE_MODEL,
    critique_model: str = DEFAULT_CRITIQUE_MODEL,
    answer_model: str = DEFAULT_ANSWER_MODEL,
    policy: LoopPolicy | None = None,
    web_search: WebSearch | None = None,
    web_fetch: WebFetch | None = None,
    rewrite_fn: RewriteFn = rewrite,
    retrieve_fn: RetrieveFn = retrieve_multi,
    critique_fn: CritiqueFn = critique,
    generate_fn: GenerateFn = generate,
) -> AgentResult:
    policy = policy or LoopPolicy()
    trace = AgentTrace()
    hints: list[str] | None = None
    iteration = 1
    queries: list[str] = [question]
    chunks: list[RetrievalResult] = []
    critique_result: CritiqueResult

    while True:
        if iteration > policy.max_iters:
            # enforce_decision only ever returns "retry" while iteration <
            # max_iters, so reaching this means that invariant broke.
            raise RuntimeError("agent loop exceeded max_iters -- enforce_decision should prevent")

        rewrite_result = rewrite_fn(provider, rewrite_model, question, hints)
        trace.record(
            iteration=iteration,
            stage="rewrite",
            summary=rewrite_result.rationale,
            queries=rewrite_result.queries,
        )

        queries = list(dict.fromkeys([question, *rewrite_result.queries]))
        chunks = retrieve_fn(index_dir, queries, RETRIEVE_K)
        trace.record(
            iteration=iteration,
            stage="retrieve",
            summary=f"{len(chunks)} chunk(s) retrieved",
            chunks=[
                {
                    "chunk_id": c.chunk_id,
                    "source_path": c.source_path,
                    "page": c.page,
                    "score": c.score,
                }
                for c in chunks
            ],
        )

        critique_result = critique_fn(
            provider,
            critique_model,
            query=question,
            chunks=chunks,
            policy=policy,
            iteration=iteration,
        )
        trace.record(
            iteration=iteration,
            stage="critique",
            summary=critique_result.rationale,
            **critique_result.model_dump(),
        )

        if critique_result.decision == "retry":
            hints = critique_result.missing
            iteration += 1
            continue
        break

    web_chunks: list[WebChunk] = []
    if critique_result.decision == "web":
        # `queries` here is whatever the last loop iteration set it to (the question plus
        # that iteration's rewrites) -- intentional, not a stale leftover: it reuses the
        # most-refined query set for the web search too, rather than re-rewriting for web.
        if policy.web_enabled and web_search is not None and web_fetch is not None:
            web_chunks = fetch_web_chunks(web_search, web_fetch, queries)
            trace.record(
                iteration=iteration,
                stage="web",
                summary=f"{len(web_chunks)} web chunk(s) fetched",
                urls=[c.url for c in web_chunks],
            )
        else:
            trace.record(
                iteration=iteration,
                stage="web",
                summary="web fallback skipped: disabled or unconfigured",
            )
            return AgentResult(
                answer=None,
                reason="web fallback is disabled or unconfigured; corpus was insufficient",
                trace=trace,
            )
        if not web_chunks:
            return AgentResult(
                answer=None,
                reason="web fallback returned no usable results; corpus was insufficient",
                trace=trace,
            )

    if critique_result.decision == "abstain":
        return AgentResult(answer=None, reason=critique_result.rationale, trace=trace)

    answer_text = generate_fn(
        provider, answer_model, query=question, chunks=chunks, web_chunks=web_chunks
    )
    cleaned_text, used_citations, illegal_found = check_citations(
        answer_text, n_source=len(chunks), n_web=len(web_chunks)
    )
    trace.record(
        iteration=iteration,
        stage="generate",
        summary="answer generated",
        illegal_citation_found=illegal_found,
        citations=used_citations,
    )

    if illegal_found and policy.citation_fail_closed:
        return AgentResult(
            answer=None,
            reason="generated answer contained an unverifiable citation (fail-closed policy)",
            trace=trace,
        )

    # Confidence reuses the last critique's grounded score; in the web branch
    # that score predates the web fetch (no re-critique of the augmented
    # context happens this phase) -- a known conservative approximation, not
    # a fresh assessment. Revisit if that proves misleading in practice.
    confidence = critique_result.grounded
    if illegal_found:
        confidence = max(0.0, confidence - ILLEGAL_CITATION_PENALTY)

    return AgentResult(
        answer=cleaned_text, confidence=confidence, citations=used_citations, trace=trace
    )


def run_safe(
    question: str,
    *,
    index_dir: Path,
    provider: Provider,
    rewrite_model: str = DEFAULT_REWRITE_MODEL,
    critique_model: str = DEFAULT_CRITIQUE_MODEL,
    answer_model: str = DEFAULT_ANSWER_MODEL,
    policy: LoopPolicy | None = None,
    web_search: WebSearch | None = None,
    web_fetch: WebFetch | None = None,
    rewrite_fn: RewriteFn = rewrite,
    retrieve_fn: RetrieveFn = retrieve_multi,
    critique_fn: CritiqueFn = critique,
    generate_fn: GenerateFn = generate,
) -> AgentResult:
    """Same as run(), but never raises. A small model can occasionally emit
    malformed JSON on both call_json's original AND repair attempt (observed
    live with qwen3.5:0.8b -- see SPEC.md's Phase 5 note); that and any other
    unexpected error becomes a clean abstain here instead of a crash, which
    matters for the UI and for a multi-case eval run where one bad response
    must not take down the rest. Callers exercising the loop's own bugs
    (tests) should call run() directly so failures aren't masked.
    """
    try:
        return run(
            question,
            index_dir=index_dir,
            provider=provider,
            rewrite_model=rewrite_model,
            critique_model=critique_model,
            answer_model=answer_model,
            policy=policy,
            web_search=web_search,
            web_fetch=web_fetch,
            rewrite_fn=rewrite_fn,
            retrieve_fn=retrieve_fn,
            critique_fn=critique_fn,
            generate_fn=generate_fn,
        )
    except Exception as e:
        trace = AgentTrace()
        trace.record(iteration=0, stage="error", summary=f"unhandled error: {e}")
        return AgentResult(answer=None, reason=f"internal error: {e}", trace=trace)
