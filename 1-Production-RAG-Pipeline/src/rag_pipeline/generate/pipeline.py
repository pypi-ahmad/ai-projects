"""Retrieve -> build cited-answer prompt -> call the selected provider ->
extract citations. Returns a GenerateResult with a retrieval trace for
observability. Shared across CLI and (later) Streamlit via `run_generate`
and the `PROVIDERS` registry.
"""

import time
from pathlib import Path

import ollama

from rag_pipeline.config import load_settings
from rag_pipeline.generate.citations import extract_citations
from rag_pipeline.generate.prompt import build_system_prompt
from rag_pipeline.generate.providers.registry import PROVIDERS
from rag_pipeline.generate.records import GenerateResult
from rag_pipeline.ingest.ocr import unload_model
from rag_pipeline.retrieve.pipeline import run_retrieve

DEFAULT_K = 5


def run_generate(
    index_dir: Path,
    query: str,
    *,
    provider: str,
    model: str | None = None,
    k: int = DEFAULT_K,
    hybrid: bool = True,
    rerank: bool = True,
) -> GenerateResult:
    if provider not in PROVIDERS:
        raise ValueError(f"provider must be one of {tuple(PROVIDERS)}, got {provider!r}")
    spec = PROVIDERS[provider]
    resolved_model = model or spec.default_model
    if resolved_model not in spec.allowed_models:
        raise ValueError(
            f"model {resolved_model!r} is not allowed for provider {provider!r}; "
            f"choose one of {spec.allowed_models}"
        )

    # Raises ProviderConfigError (caller's job to catch) before any retrieval
    # work happens, if the provider's required env var(s) are missing.
    provider_instance = spec.factory()

    results = run_retrieve(index_dir, query, k=k, hybrid=hybrid, rerank=rerank)
    system_prompt = build_system_prompt(results)

    start = time.monotonic()
    answer = provider_instance.complete(system=system_prompt, user=query, model=resolved_model)
    latency_ms = (time.monotonic() - start) * 1000

    if provider == "ollama":
        # Only the ollama provider is a local, VRAM-resident model -- the 3
        # cloud providers have nothing to unload. Matches retrieve's policy
        # of not leaving a heavy model resident after its stage finishes.
        unload_model(ollama.Client(host=load_settings().ollama_host), resolved_model)

    return GenerateResult(
        answer_markdown=answer,
        citations=extract_citations(answer, results),
        model=resolved_model,
        latency_ms=latency_ms,
        retrieval_trace=[
            {
                "chunk_id": r.chunk_id,
                "score": r.score,
                "fusion_rank": r.fusion_rank,
                "rerank_score": r.rerank_score,
                "source_path": r.source_path,
                "page": r.page,
            }
            for r in results
        ],
    )
