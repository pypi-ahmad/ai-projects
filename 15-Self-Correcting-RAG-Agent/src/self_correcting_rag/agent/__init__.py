"""The self-correction core: rewrite, critique, generate, citation checking, and the loop
that ties them together (loop.py). Must not talk to Qdrant/bm25s directly -- retrieval goes
through retrieve/, not this package. Start reading at agent/schemas.py for the data shapes,
then agent/loop.py for the control flow.
"""
