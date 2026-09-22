"""Tests for src.extract's model-client construction (`_build_llm`) and the
dormant invoice extract/crop path (`extract_invoice`, `extract_regions`,
`crop_and_extract`), all via `tests/fake_llm.py`'s `FakeLLM` -- no real
network call. `_invoke_structured`'s own diagnostic/error-mapping behavior
is covered separately in test_diagnostics.py.

Next: src/extract.py.
"""

from __future__ import annotations

import pytest

from src import extract
from src.schema import Invoice, LineItem, Region, ValidationErrorItem, ValidationReport


from tests.fake_llm import FakeLLM as _FakeLLM


@pytest.mark.parametrize("model", ["gpt-6-sol"])
def test_client_uses_selected_model_and_existing_settings(monkeypatch, model):
    monkeypatch.setenv("OPENAI_API_KEY", "test-not-a-real-key")
    monkeypatch.setenv("REASONING_EFFORT", "medium")
    captured = {}

    def capture(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(extract, "ChatOpenAI", capture)
    extract._build_llm(model=model)
    assert captured["model"] == model
    assert "temperature" not in captured
    assert captured["reasoning_effort"] == "medium"


def test_client_rejects_unsupported_model_before_api_call():
    with pytest.raises(extract.ExtractConfigError, match="Unsupported model"):
        extract._build_llm(model="unlisted-model")


def _good_invoice() -> Invoice:
    return Invoice(
        invoice_number="INV-1001",
        vendor=None,
        invoice_date=None,
        currency=None,
        line_items=[LineItem(description="Widget A", quantity=3, unit_price=10.0, amount=30.0)],
        subtotal=30.0,
        tax=0.0,
        grand_total=30.0,
    )


def test_extract_invoice_returns_invoice(monkeypatch):
    inv = _good_invoice()
    monkeypatch.setattr(extract, "_build_llm", lambda: _FakeLLM(inv))

    result = extract.extract_invoice("Zm9v", "image/png")

    assert result == inv


def test_extract_regions_empty_when_llm_call_fails(monkeypatch):
    def _boom():
        raise RuntimeError("gateway rejected the request")

    monkeypatch.setattr(extract, "_build_llm", _boom)

    report = ValidationReport(
        ok=False, errors=[ValidationErrorItem(code="subtotal_mismatch", msg="x")]
    )
    result = extract.extract_regions("Zm9v", "image/png", report)

    assert result == []


def test_extract_regions_empty_when_model_returns_none(monkeypatch):
    monkeypatch.setattr(extract, "_build_llm", lambda: _FakeLLM(None))

    report = ValidationReport(ok=True, errors=[])
    result = extract.extract_regions("Zm9v", "image/png", report)

    assert result == []


def test_crop_and_extract_line_item(monkeypatch, tmp_path):
    from PIL import Image

    calls = {}

    def _fake_crop(image, bbox):
        calls["bbox"] = bbox
        return Image.new("RGB", (10, 10))

    monkeypatch.setattr(extract, "crop_image_bbox", _fake_crop)
    monkeypatch.chdir(tmp_path)

    line_item = LineItem(description="Widget A", quantity=3, unit_price=10.0, amount=30.0)
    monkeypatch.setattr(extract, "_build_llm", lambda: _FakeLLM(line_item))

    full_image = Image.new("RGB", (100, 100))
    region = Region(
        id="r1", field_or_line_index="line_items[0]", conf=0.4, bbox_xyxy=(0.1, 0.1, 0.5, 0.5),
        reason=None,
    )

    result = extract.crop_and_extract(full_image, region, "hint text", "abc123")

    assert result == line_item
    assert calls["bbox"] == (0.1, 0.1, 0.5, 0.5)
    assert (tmp_path / "data" / "crops" / "abc123" / "r1.png").exists()


def test_crop_and_extract_header_field(monkeypatch, tmp_path):
    from PIL import Image

    monkeypatch.setattr(extract, "crop_image_bbox", lambda image, bbox: Image.new("RGB", (10, 10)))
    monkeypatch.chdir(tmp_path)

    class _FakeFieldResult:
        def model_dump(self):
            return {"grand_total": 88.0}

    monkeypatch.setattr(extract, "_build_llm", lambda: _FakeLLM(_FakeFieldResult()))

    full_image = Image.new("RGB", (100, 100))
    region = Region(
        id="r2", field_or_line_index="grand_total", conf=0.5, bbox_xyxy=(0.6, 0.8, 0.9, 0.9),
        reason=None,
    )

    result = extract.crop_and_extract(full_image, region, "hint text", "abc123")

    assert result == {"grand_total": 88.0}
    assert (tmp_path / "data" / "crops" / "abc123" / "r2.png").exists()


def test_missing_api_key_raises_config_error(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(extract.ExtractConfigError):
        extract.extract_invoice("Zm9v", "image/png")
