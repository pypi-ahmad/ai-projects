"""Package marker for `src` -- the ADE pipeline (preprocess -> parse -> END,
plus the dormant invoice extract/validate/crop path; see docs/ARCHITECTURE.md).

Deliberately empty: importers reach into specific submodules directly (e.g.
`from src.graph import run_graph`), so this file must not import submodules
itself or add other import-time side effects that could tangle into a
circular import across preprocess/parse/extract/schema.

Next: src/graph.py for the active graph's entry point.
"""
