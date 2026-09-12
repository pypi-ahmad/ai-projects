"""Ingest stage: walk an input folder, parse/OCR/translate each file, write one JSONL
record per file (ingest.jsonl). Must not chunk, embed, or index -- that starts in
rag_pipeline.chunk, which reads this stage's output. See pipeline.py for the entry point.
"""
