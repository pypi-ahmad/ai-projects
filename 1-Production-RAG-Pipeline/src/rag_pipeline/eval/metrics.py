"""Pure metric functions: recall@k and citation hit rate. Both take the
already-computed retrieve/generate results, so they need no network access
and are cheap to unit test.
"""

import re

from rag_pipeline.eval.records import EvalCase
from rag_pipeline.retrieve.records import RetrievalResult

_CITATION_RE = re.compile(r"\[S(\d+)\]")


def recall_at_k(case: EvalCase, results: list[RetrievalResult]) -> float | None:
    """Fraction of the case's labeled relevant chunks that appear anywhere in
    the retrieved top-k. Returns None if the case has no labeled relevant set
    at all (nothing to score against), not zero.
    """
    if case.relevant_chunk_ids:
        relevant = set(case.relevant_chunk_ids)
        hit = any(r.chunk_id in relevant for r in results)
        return 1.0 if hit else 0.0
    if case.relevant_sources:
        wanted = {(s["source_path"], s["page"]) for s in case.relevant_sources}
        hit = any((r.source_path, r.page) in wanted for r in results)
        return 1.0 if hit else 0.0
    return None


def citation_hit_rate(answer_markdown: str, num_results: int) -> float | None:
    """Of the distinct [Sn] indices the model actually cited, what fraction
    are within the retrieved set (1..num_results)? Catches a model citing a
    source number that was never given ("hallucinated" citation), which
    `generate.citations.extract_citations` silently drops rather than
    surfaces -- this metric measures how often that drop actually happens.
    Returns None if the answer cited nothing at all (undefined, not zero).
    """
    cited = {int(m.group(1)) for m in _CITATION_RE.finditer(answer_markdown)}
    if not cited:
        return None
    valid = {n for n in cited if 1 <= n <= num_results}
    return len(valid) / len(cited)
