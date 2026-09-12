"""SQLite + JSONL export. See docs/ARCHITECTURE.md and docs/SCHEMA.md."""

from obs.export.jsonl import JsonlExporter
from obs.export.query import get_trace, query
from obs.export.sqlite import SqliteExporter
from obs.trace import register_exporter

__all__ = ["JsonlExporter", "SqliteExporter", "get_trace", "query", "register_default_exporters"]


def register_default_exporters() -> None:
    """Register both exporters with their default paths (data/traces/, data/obs.db).

    Not called automatically on import - callers (CLI, UI) opt in explicitly.
    """
    register_exporter(JsonlExporter())
    register_exporter(SqliteExporter())
