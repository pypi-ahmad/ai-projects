"""Chunk stage: split each ingested page's text into token-budget windows, write one
JSONL record per chunk (chunks.jsonl). Must not embed or index -- that starts in
rag_pipeline.index, which reads this stage's output. See pipeline.py for the entry point.
"""
