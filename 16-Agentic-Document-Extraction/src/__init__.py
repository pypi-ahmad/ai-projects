"""Package marker for the document-to-Markdown pipeline.

Deliberately empty: importers reach into specific submodules directly (e.g.
`from src.graph import run_graph`), so this file must not import submodules
itself or add other import-time side effects that could tangle into a
circular import across preprocessing, parsing, and rendering.

Next: src/graph.py for the active graph's entry point.
"""
