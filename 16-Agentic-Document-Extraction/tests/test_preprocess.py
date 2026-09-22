"""Tests for src.preprocess -- page counting, PNG/PDF loading into a
model-ready base64 payload, and the 1-based inclusive start_page/end_page
range honored by `preprocess_pages`.

Next: src/preprocess.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from src.preprocess import PreprocessError, preprocess, preprocess_pages
from tests.fixtures.make_invoice_png import main as make_fixtures

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module", autouse=True)
def _ensure_fixtures():
    if not (FIXTURES_DIR / "invoice.png").exists():
        make_fixtures()


def test_missing_file_raises():
    with pytest.raises(PreprocessError):
        preprocess(FIXTURES_DIR / "does_not_exist.png")


def test_png_returns_base64():
    result = preprocess(FIXTURES_DIR / "invoice.png")
    assert result["mime"] == "image/png"
    assert isinstance(result["base64"], str) and len(result["base64"]) > 0
    assert result["pages"] == 1
    assert result["width"] > 0 and result["height"] > 0


def test_sha_stable():
    a = preprocess(FIXTURES_DIR / "invoice.png")
    b = preprocess(FIXTURES_DIR / "invoice.png")
    assert a["doc_sha256"] == b["doc_sha256"]
    assert len(a["doc_sha256"]) == 64


def test_pdf_first_page(tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    Image.new("RGB", (200, 100), "white").save(pdf_path, "PDF")

    result = preprocess(pdf_path)

    assert result["mime"] == "image/png"
    assert result["pages"] == 1
    assert result["width"] > 0 and result["height"] > 0


def _make_multi_page_pdf(path: Path) -> None:
    pages = [Image.new("RGB", (200, 100), color) for color in ("white", "red", "blue", "green")]
    pages[0].save(path, save_all=True, append_images=pages[1:])


def test_preprocess_pages_defaults_to_whole_document(tmp_path):
    pdf_path = tmp_path / "multi.pdf"
    _make_multi_page_pdf(pdf_path)

    result = preprocess_pages(pdf_path)

    assert [p["page"] for p in result] == [1, 2, 3, 4]
    assert result[0]["doc_sha256"] == result[1]["doc_sha256"]


def test_preprocess_pages_explicit_range(tmp_path):
    pdf_path = tmp_path / "multi.pdf"
    _make_multi_page_pdf(pdf_path)

    result = preprocess_pages(pdf_path, start_page=2, end_page=3)

    assert [p["page"] for p in result] == [2, 3]


def test_preprocess_pages_end_page_none_goes_to_last_page(tmp_path):
    pdf_path = tmp_path / "multi.pdf"
    _make_multi_page_pdf(pdf_path)

    result = preprocess_pages(pdf_path, start_page=3, end_page=None)

    assert [p["page"] for p in result] == [3, 4]


def test_preprocess_pages_single_image_is_one_page():
    result = preprocess_pages(FIXTURES_DIR / "invoice.png")
    assert len(result) == 1
    assert result[0]["page"] == 1


@pytest.mark.parametrize("start,end", [(0, 1), (2, 1), (1, 5), (5, None)])
def test_invalid_pdf_ranges_fail(tmp_path, start, end):
    source = tmp_path / "multi.pdf"
    _make_multi_page_pdf(source)
    with pytest.raises(PreprocessError):
        preprocess_pages(source, start_page=start, end_page=end)


def test_resolution_profiles_and_no_raster_upscaling(tmp_path):
    source = tmp_path / "tall.pdf"
    Image.new("RGB", (1000, 2000), "white").save(source, "PDF")
    baseline = preprocess_pages(source)[0]
    candidate = preprocess_pages(source, pdf_dpi=300, max_long_edge=3200)[0]
    assert (baseline["width"], baseline["height"]) == (800, 1600)
    assert (candidate["width"], candidate["height"]) == (1600, 3200)
    raster = tmp_path / "small.png"
    Image.new("RGB", (100, 200)).save(raster)
    page = preprocess_pages(raster, pdf_dpi=300, max_long_edge=3200)[0]
    assert (page["width"], page["height"]) == (100, 200)
    with pytest.raises(PreprocessError):
        preprocess_pages(raster, start_page=2)
