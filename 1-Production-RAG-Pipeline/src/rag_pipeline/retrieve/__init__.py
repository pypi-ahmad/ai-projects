"""Retrieve stage: embed a query, search the dense and BM25 stores, fuse with RRF, and
rerank -- returns ranked chunks only, never an answer. Must not call a generation
provider -- that starts in rag_pipeline.generate, which calls this stage internally.
See pipeline.py for the entry point.
"""
