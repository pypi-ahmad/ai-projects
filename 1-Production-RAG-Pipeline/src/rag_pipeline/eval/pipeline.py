"""Runs the full retrieve+generate pipeline against a labeled qa.jsonl set
and computes recall@k, citation hit rate, latency, and (optionally) an
LLM-judged faithfulness score.
"""

import json
from pathlib import Path

import ollama

from rag_pipeline.config import load_settings
from rag_pipeline.eval.judge import score_faithfulness
from rag_pipeline.eval.metrics import citation_hit_rate, recall_at_k
from rag_pipeline.eval.records import EvalCase, EvalCaseResult, EvalReport
from rag_pipeline.generate.pipeline import DEFAULT_K, run_generate
from rag_pipeline.generate.prompt import build_context_block
from rag_pipeline.retrieve.pipeline import run_retrieve


def load_cases(qa_path: Path) -> list[EvalCase]:
    cases = []
    with qa_path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                data = json.loads(line)
                cases.append(EvalCase(**data))
    return cases


def run_eval(
    index_dir: Path,
    qa_path: Path,
    *,
    provider: str = "ollama",
    model: str | None = None,
    k: int = DEFAULT_K,
    judge_model: str | None = None,
) -> EvalReport:
    """judge_model=None (the default) skips faithfulness scoring entirely --
    it costs an extra Ollama call per case, so it's opt-in, not automatic.
    """
    cases = load_cases(qa_path)
    judge_client = ollama.Client(host=load_settings().ollama_host) if judge_model else None

    results = []
    for case in cases:
        retrieved = run_retrieve(index_dir, case.question, k=k)
        generated = run_generate(index_dir, case.question, provider=provider, model=model, k=k)

        faithfulness = None
        if judge_model and judge_client is not None:
            context = build_context_block(retrieved)
            faithfulness = score_faithfulness(
                judge_client, judge_model, case.question, context, generated.answer_markdown
            )

        results.append(
            EvalCaseResult(
                id=case.id,
                question=case.question,
                recall_at_k=recall_at_k(case, retrieved),
                citation_hit_rate=citation_hit_rate(generated.answer_markdown, len(retrieved)),
                latency_ms=generated.latency_ms,
                faithfulness=faithfulness,
            )
        )

    return EvalReport(k=k, judge_model=judge_model, cases=results)
