"""Index stage: embed chunks into a Qdrant local-mode vector store and build a matching
bm25s lexical index. Must not answer queries itself -- that starts in rag_pipeline.retrieve,
which reads both stores this stage writes. See pipeline.py for the entry point.
"""
