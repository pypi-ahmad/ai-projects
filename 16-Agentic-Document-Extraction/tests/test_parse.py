"""Tests for sequential, context-aware document layout parsing.

Next: src/parse.py.
"""

from __future__ import annotations

import json
import pytest
from pathlib import Path

from openai import ContentFilterFinishReasonError

from src import parse as parse_module
from src.layout import BBox, ParseBlock, ParsePage

FIXTURE_PATH = (Path(__file__).parent / "fixtures" / "invoice.png").resolve()


from tests.fake_llm import FakeLLM as _FakeLLM


def test_parse_document_writes_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    fake_page = ParsePage(
        page=1,
        width_px=900,
        height_px=620,
        blocks=[
            ParseBlock(
                id="b1", type="title", text="INVOICE",
                bbox=BBox(page=1, xyxy=(0.0, 0.0, 0.3, 0.05)), conf=None, table=None,
            ),
            ParseBlock(
                id="b2", type="text", text="Invoice #: INV-1001", bbox=None,
                conf=None, table=None,
            ),
        ],
    )
    monkeypatch.setattr(parse_module, "_build_llm", lambda **kwargs: _FakeLLM(fake_page))

    result = parse_module.parse_document(str(FIXTURE_PATH))

    assert len(result.pages) == 1
    assert len(result.pages[0].blocks) >= 1
    assert result.pages[0].blocks[0].text == "INVOICE"
    assert result.pages[0].page == 1

    out_path = Path("data/parse") / f"{result.doc_sha}.json"
    assert out_path.exists()
    on_disk = json.loads(out_path.read_text(encoding="utf-8"))
    assert on_disk["doc_sha"] == result.doc_sha
    assert len(on_disk["pages"][0]["blocks"]) == 2


def test_parse_document_respects_page_range(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from PIL import Image

    pdf_path = tmp_path / "multi.pdf"
    pages_imgs = [Image.new("RGB", (200, 100), c) for c in ("white", "red", "blue")]
    pages_imgs[0].save(pdf_path, save_all=True, append_images=pages_imgs[1:])

    fake_page = ParsePage(page=1, width_px=1, height_px=1, blocks=[])
    monkeypatch.setattr(parse_module, "_build_llm", lambda **kwargs: _FakeLLM(fake_page))

    result = parse_module.parse_document(str(pdf_path), start_page=2, end_page=3)

    assert [p.page for p in result.pages] == [2, 3]


def test_parse_document_keeps_pages_not_rejected_by_content_filter(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from PIL import Image

    pdf_path = tmp_path / "multi.pdf"
    page_images = [Image.new("RGB", (200, 100), color) for color in ("white", "red", "blue")]
    page_images[0].save(pdf_path, save_all=True, append_images=page_images[1:])

    def fake_parse_page(image_b64, mime, page_number, width_px, height_px, **kwargs):
        if page_number == 2:
            raise ContentFilterFinishReasonError()
        return ParsePage(page=page_number, width_px=width_px, height_px=height_px, blocks=[])

    monkeypatch.setattr(parse_module, "parse_page", fake_parse_page)

    result = parse_module.parse_document(pdf_path)

    assert [page.page for page in result.pages] == [1, 3]
    assert result.content_filtered_pages == [2]
    saved = json.loads((Path("data/parse") / f"{result.doc_sha}.json").read_text(encoding="utf-8"))
    assert saved["content_filtered_pages"] == [2]


@pytest.mark.parametrize("selected_model", ["gpt-6-sol"])
def test_sequential_outcomes_keep_page_identity_and_context(tmp_path, monkeypatch, selected_model):
    from src.diagnostics import ExtractionCallError, PageDiagnostic

    monkeypatch.chdir(tmp_path)
    payloads = [dict(base64="", mime="image/png", page=n, width=100, height=100, doc_sha256="mixed")
                for n in (1, 2, 3)]
    monkeypatch.setattr(parse_module, "preprocess_pages", lambda *a, **k: payloads)
    contexts = []

    def fake_parse_page(image, mime, page_number, width, height, *, diagnostics, model, **kwargs):
        assert model == selected_model
        contexts.append(kwargs["document_context"])
        outcome = {1: "parsed", 2: "refused", 3: "content_filtered"}[page_number]
        diagnostic = PageDiagnostic(outcome=outcome, request_id=f"req-{page_number}")
        diagnostics.append(diagnostic)
        if outcome != "parsed":
            raise ExtractionCallError(diagnostic)
        return ParsePage(page=page_number, width_px=width, height_px=height, blocks=[
            ParseBlock(id=f"p{page_number}", type="heading", text="Previous heading",
                       bbox=None, conf=None, table=None)])

    monkeypatch.setattr(parse_module, "parse_page", fake_parse_page)
    result = parse_module.parse_document("unused", model=selected_model)
    assert [p.page for p in result.pages] == [1]
    assert result.content_filtered_pages == [3]
    assert [(d.page, d.request_id, d.outcome) for d in result.page_diagnostics] == [
        (1, "req-1", "parsed"), (2, "req-2", "refused"), (3, "req-3", "content_filtered")]
    assert json.loads(Path("data/parse/mixed.json").read_text())["page_diagnostics"][1]["outcome"] == "refused"
    assert contexts == ["", "Previous heading", "Previous heading"]


def test_all_failed_diagnostics_are_saved(tmp_path, monkeypatch):
    from src.diagnostics import ExtractionCallError, PageDiagnostic

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(parse_module, "preprocess_pages", lambda *a, **k: [
        dict(base64="", mime="image/png", page=2, width=100, height=100, doc_sha256="failed")])

    def fail(*args, **kwargs):
        raise ExtractionCallError(PageDiagnostic(outcome="http_error", http_status=429))

    monkeypatch.setattr(parse_module, "parse_page", fail)
    result = parse_module.parse_document("unused", start_page=2, end_page=2)
    assert result.pages == []
    saved = json.loads(Path("data/parse/failed.json").read_text())
    assert saved["page_diagnostics"][0]["page"] == 2
    assert saved["page_diagnostics"][0]["http_status"] == 429


def test_progress_reports_completion_in_source_order(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(parse_module, "preprocess_pages", lambda *a, **k: [
        dict(base64="", mime="image/png", page=n, width=100, height=100, doc_sha256="progress") for n in (1, 2)])

    def parse(image, mime, page_number, width, height, **kwargs):
        return ParsePage(page=page_number, width_px=width, height_px=height, blocks=[])

    events = []
    def progress(event):
        events.append(event)

    monkeypatch.setattr(parse_module, "parse_page", parse)
    result = parse_module.parse_document("unused", on_progress=progress)
    assert [p.page for p in result.pages] == [1, 2]
    assert [e["completed"] for e in events] == [1, 2]
    assert events[-1] == dict(completed=2, total=2, successful=2, failed=0)
