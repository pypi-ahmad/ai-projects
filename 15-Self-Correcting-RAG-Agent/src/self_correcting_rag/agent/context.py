"""Formats retrieved chunks as tagged, citable context blocks. Shared by the
critique step now and by answer synthesis in a later phase -- see
docs/CITATIONS.md for the `[S#]` tagging rule this mirrors.
"""

from self_correcting_rag.retrieve.records import RetrievalResult
from self_correcting_rag.web.records import WebChunk


def format_context_blocks(
    chunks: list[RetrievalResult], web_chunks: list[WebChunk] | None = None
) -> str:
    parts = [
        f"[S{i}] ({chunk.source_path}#page{chunk.page}):\n{chunk.text}"
        for i, chunk in enumerate(chunks, start=1)
    ]
    parts += [
        f"[W{i}] ({chunk.url}):\n{chunk.text}" for i, chunk in enumerate(web_chunks or [], start=1)
    ]
    return "\n\n".join(parts) if parts else "(no context retrieved)"
