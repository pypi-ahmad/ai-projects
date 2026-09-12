"""Pointwise reranking via qwen3.5:0.8b: score each candidate 0-1 against the
query. Batched to cut round-trips, with a per-item fallback if a batch
response doesn't parse cleanly into exactly one number per candidate.
"""

import logging
import re

import ollama

from rag_pipeline.retrieve.records import Candidate

RERANK_MODEL = "qwen3.5:0.8b"
RERANK_BATCH_SIZE = 5

logger = logging.getLogger(__name__)

_NUMBER_RE = re.compile(r"[-+]?\d*\.?\d+")


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _parse_score(text: str) -> float | None:
    match = _NUMBER_RE.search(text)
    if not match:
        return None
    try:
        return _clamp01(float(match.group()))
    except ValueError:
        return None


def _score_single(client: ollama.Client, query: str, text: str) -> float:
    prompt = (
        "Score how relevant this passage is to the query, on a scale from 0.0 "
        "(irrelevant) to 1.0 (highly relevant). Respond with only the number, "
        f"nothing else.\n\nQuery: {query}\nPassage: {text}"
    )
    response = client.generate(model=RERANK_MODEL, prompt=prompt)
    score = _parse_score(response.response or "")
    if score is None:
        logger.warning("could not parse a rerank score from model output; scoring 0.0")
        return 0.0
    return score


def _score_batch(client: ollama.Client, query: str, texts: list[str]) -> list[float] | None:
    numbered = "\n".join(f"[{i + 1}] {text}" for i, text in enumerate(texts))
    prompt = (
        f"Score how relevant each of the {len(texts)} passages below is to the "
        "query, on a scale from 0.0 (irrelevant) to 1.0 (highly relevant).\n\n"
        f"Query: {query}\n\nPassages:\n{numbered}\n\n"
        f"Respond with exactly {len(texts)} lines, each containing only a number "
        "between 0 and 1, one per passage in order. No other text."
    )
    response = client.generate(model=RERANK_MODEL, prompt=prompt)
    lines = [line for line in (response.response or "").strip().splitlines() if line.strip()]
    if len(lines) != len(texts):
        return None
    scores = [_parse_score(line) for line in lines]
    if any(score is None for score in scores):
        return None
    return [score for score in scores if score is not None]


def rerank(client: ollama.Client, query: str, candidates: list[Candidate]) -> list[Candidate]:
    """Sets `rerank_score` on each candidate dict (mutated in place) and
    returns them sorted by rerank_score descending.
    """
    for start in range(0, len(candidates), RERANK_BATCH_SIZE):
        batch = candidates[start : start + RERANK_BATCH_SIZE]
        texts = [c["text"] for c in batch]
        scores = _score_batch(client, query, texts) if len(batch) > 1 else None
        if scores is None:
            scores = [_score_single(client, query, text) for text in texts]
        for candidate, score in zip(batch, scores, strict=True):
            candidate["rerank_score"] = score
    # Every candidate's rerank_score was just set above, so `or 0.0` here is
    # purely a type-narrowing no-op (None or 0.0 never actually happens).
    return sorted(candidates, key=lambda c: c["rerank_score"] or 0.0, reverse=True)
