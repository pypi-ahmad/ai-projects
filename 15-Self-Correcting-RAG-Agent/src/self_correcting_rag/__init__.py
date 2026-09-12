"""Self-correcting RAG agent: rewrite, retrieve, critique, fallback-or-abstain, cited answer.

Package layout, roughly in read order: config.py (settings + model/provider allowlists) ->
llm/ (provider clients) -> ingest/ + index/ (build a corpus into a queryable index) ->
retrieve/ (hybrid search) -> agent/ (the rewrite/critique/generate loop, agent/loop.py's
run()/run_safe() is the main entry point) -> web/ (optional web fallback) -> eval/ and ui/
(two callers of the agent loop). See docs/ARCHITECTURE.md for the data-flow diagram.
"""
