"""End-to-end tests for the active `preprocess -> parse -> END` graph
(src/graph.py), with `parse_document` faked so no real model call happens.
Covers status/parse_error mapping across success, total failure, and
partial (some pages content-filtered) outcomes.

Next: src/graph.py.
"""

from __future__ import annotations

from pathlib import Path
import pytest

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


def test_overlapping_runs_isolate_usage_and_artifacts(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, get_ident
    from src import usage

    monkeypatch.chdir(tmp_path)
    barrier = Barrier(2)
    monkeypatch.setattr(graph_module, "preprocess", lambda path: dict(doc_sha256="same", base64="", mime="image/png"))
    monkeypatch.setattr(graph_module, "annotate_document", lambda *a, **k: (_ for _ in ()).throw(ValueError("skip")))

    def parse(path, **kwargs):
        barrier.wait(timeout=5)
        usage.record(path, "gpt-6-sol", dict(input_tokens=int(path), output_tokens=1), entries=kwargs["usage_entries"])
        kwargs["on_progress"](dict(completed=1, total=1, successful=1, failed=0))
        return ParseResult(doc_sha="same", pages=[ParsePage(page=1, width_px=1, height_px=1, blocks=[])])

    monkeypatch.setattr(graph_module, "parse_document", parse)

    def run(path):
        caller = get_ident()
        events = []
        result = graph_module.run_graph(path, on_progress=lambda event: events.append((event, get_ident())))
        assert len(events) == 1 and events[0][1] == caller
        return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = list(pool.map(run, ["100", "200"]))
    assert a["token_usage"][0]["input_tokens"] == 100
    assert b["token_usage"][0]["input_tokens"] == 200
    assert a["markdown_path"] != b["markdown_path"]
    assert Path(a["markdown_path"]).exists() and Path(b["markdown_path"]).exists()


def test_usage_survives_post_request_failure(tmp_path, monkeypatch):
    from src import usage
    monkeypatch.chdir(tmp_path)

    def fail(path, **kwargs):
        usage.record("parse_page", "gpt-6-sol", dict(input_tokens=123, output_tokens=10), entries=kwargs["usage_entries"])
        raise OSError("artifact write failed")

    monkeypatch.setattr(graph_module, "parse_document", fail)
    result = graph_module.run_graph(str(FIXTURE_PATH))
    assert result["status"] == "parse_failed"
    assert result["token_usage"][0]["input_tokens"] == 123


def test_graph_rejects_other_models_before_preprocessing(monkeypatch):
    monkeypatch.setattr(graph_module, "preprocess", lambda *a: pytest.fail("Unexpected preprocessing"))
    with pytest.raises(ValueError, match="Unsupported model"):
        graph_module.run_graph("unused", model="gpt-6-luna")


def test_direct_compiled_graph_initializes_run_state(tmp_path, monkeypatch):
    from src import usage
    monkeypatch.chdir(tmp_path)

    def parse(path, **kwargs):
        assert Path(kwargs["output_dir"]).parent == Path("data/parse/runs")
        usage.record("parse_page", "gpt-6-sol", dict(input_tokens=42, output_tokens=1), entries=kwargs["usage_entries"])
        return ParseResult(doc_sha="empty", pages=[])

    monkeypatch.setattr(graph_module, "parse_document", parse)
    result = graph_module.build_graph().invoke(dict(image_path=str(FIXTURE_PATH)))
    assert result["model"] == "gpt-6-sol" and result["run_id"]
    assert result["token_usage"][0]["input_tokens"] == 42


def test_partial_parse_keeps_artifacts_and_reports_filtered_pages(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from PIL import Image
    source = tmp_path / "two.pdf"
    image = Image.new("RGB", (100, 100), "white")
    image.save(source, "PDF", save_all=True, append_images=[image])

    def fake_parse_document(path, start_page=1, end_page=None, **kwargs):
        return ParseResult(
            doc_sha="partial",
            pages=[ParsePage(page=1, width_px=900, height_px=620, blocks=[])],
            content_filtered_pages=[2],
        )

    monkeypatch.setattr(graph_module, "parse_document", fake_parse_document)

    result = graph_module.run_graph(str(source))

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
