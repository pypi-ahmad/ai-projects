"""Generate stage: run retrieve, build a citation-tagged prompt, call the selected LLM
provider, and extract which citations were actually used. See providers/ for the
provider implementations this stage dispatches to, and pipeline.py for the entry point.
"""
