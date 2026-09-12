"""Local-first, hybrid-retrieval RAG pipeline: ingest -> chunk -> index -> retrieve -> generate,
plus eval and a Streamlit UI on top. See SPEC.md for the phase plan and hardware constraints,
and rag_pipeline.config for the fixed model/provider allowlists every stage draws from.
"""
