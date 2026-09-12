"""Eval stage: run retrieve+generate over a labeled qa.jsonl set and score recall@k,
citation hit rate, latency, and (opt-in) LLM-judged faithfulness. Must not be required
for the ingest/query path to work -- this stage only reads an already-built index.
See pipeline.py for the entry point and metrics.py for what each score actually measures.
"""
