"""Parse which [Sn] citation tags actually appear in a generated answer, and
map them back to the retrieved chunks' source metadata.
"""

import re

from rag_pipeline.retrieve.records import RetrievalResult

_CITATION_RE = re.compile(r"\[S(\d+)\]")


def extract_citations(answer_markdown: str, results: list[RetrievalResult]) -> list[dict]:
    """Citations actually used in the answer, deduplicated, in first-
    appearance order. An out-of-range index (the model citing a source
    number that was never in the context) is silently dropped rather than
    raising -- it's a model mistake, not a pipeline error.
    """
    seen: list[int] = []
    for match in _CITATION_RE.finditer(answer_markdown):
        n = int(match.group(1))
        if n not in seen:
            seen.append(n)

    citations = []
    for n in seen:
        if 1 <= n <= len(results):
            result = results[n - 1]
            citations.append(
                {
                    "index": n,
                    "chunk_id": result.chunk_id,
                    "source_path": result.source_path,
                    "page": result.page,
                }
            )
    return citations
