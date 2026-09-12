"""Embeds ingest/'s chunks and stores them in two on-disk indexes: a Qdrant dense
collection (vector_store.py) and a bm25s lexical index (lexical_store.py). Must not perform
retrieval or fusion -- that's retrieve/'s job. Start reading at index/pipeline.py.
"""
