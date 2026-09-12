"""Hybrid search over an index/-built index: dense (dense.py) + lexical (lexical.py),
combined by rank via Reciprocal Rank Fusion (fusion.py). Must not call an LLM for anything
but embedding the query -- rewriting and critiquing retrieved results belong to agent/.
Start reading at retrieve/pipeline.py.
"""
