"""End-to-end tests for the active `preprocess -> parse -> END` graph
(src/graph.py), with `parse_document` faked so no real model call happens.
Covers status/parse_error mapping across success, total failure, and
partial (some pages content-filtered) outcomes.

Next: src/graph.py.
"""

from __future__ import annotations

from pathlib import Path

from src import graph as graph_module
from src.schema import ParsePage, ParseResult

FIXTURE_PATH = (Path(__file__).parent / "fixtures" / "invoice.png").resolve()


def test_parse_success_sets_status_and_artifacts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    from src.schema import ParseResult

    def fake_parse_document(path, start_page=1, end_page=None, **kwargs):
        import hashlib

        doc_sha = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        return ParseResult(
            doc_sha=doc_sha,
            pages=[ParsePage(page=1, width_px=900, height_px=620, blocks=[])],
        )

    monkeypatch.setattr(graph_module, "parse_document", fake_parse_document)

    result = graph_module.run_graph(str(FIXTURE_PATH))

    assert result["status"] == "parsed"
    assert result["parse_error"] is None
    assert result["markdown"] is not None
    assert result["annotated_pdf_path"] is not None
    assert Path(result["annotated_pdf_path"]).exists()


def test_parse_failure_sets_status_and_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def fake_parse_document(path, start_page=1, end_page=None, **kwargs):
        raise RuntimeError("rejected by the content filter")

    monkeypatch.setattr(graph_module, "parse_document", fake_parse_document)

    result = graph_module.run_graph(str(FIXTURE_PATH))

    assert result["status"] == "parse_failed"
    assert "content filter" in result["parse_error"]
    assert result["markdown"] is None
    assert result["annotated_pdf_path"] is None


def test_partial_parse_keeps_artifacts_and_reports_filtered_pages(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def fake_parse_document(path, start_page=1, end_page=None, **kwargs):
        return ParseResult(
            doc_sha="partial",
            pages=[ParsePage(page=1, width_px=900, height_px=620, blocks=[])],
            content_filtered_pages=[2],
        )

    monkeypatch.setattr(graph_module, "parse_document", fake_parse_document)

    result = graph_module.run_graph(str(FIXTURE_PATH))

    assert result["status"] == "parsed_partial"
    assert result["parse_error"] == "Pages rejected by content filter: 2"
    assert result["markdown"] is not None
    assert result["annotated_pdf_path"] is not None


def test_all_filtered_pages_fail_without_markdown_or_annotation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def fake_parse_document(path, start_page=1, end_page=None, **kwargs):
        return ParseResult(doc_sha="filtered", pages=[], content_filtered_pages=[1])

    monkeypatch.setattr(graph_module, "parse_document", fake_parse_document)

    result = graph_module.run_graph(str(FIXTURE_PATH))

    assert result["status"] == "parse_failed"
    assert result["parse_error"] == "Pages rejected by content filter: 1"
    assert result["markdown"] is None
    assert result["annotated_pdf_path"] is None
