"""Extract-from-file: text files skip OCR; images/PDFs go through
PaddleOCR (primary) then qwen3-vl:2b via Ollama (fallback). No real OCR
model or Ollama server required — PaddleOCR is faked via sys.modules
injection (it genuinely isn't installed in this venv, which is also what
lets the "falls back" tests exercise the real ImportError path), and the
Ollama fallback uses a fake complete()-based provider.
Run: uv run python tests/test_file_input.py
"""

import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from unittest import mock

from engine.file_input import OcrError, is_text_file, load_text_from_file
from providers.base import ProviderResponse

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class FakeVlProvider:
    def __init__(self, text: str = "", error: Exception | None = None):
        self.text = text
        self.error = error
        self.complete_calls: list[list[dict]] = []
        self.unload_calls = 0

    def complete(self, messages, *, json_schema=None, temperature=0.0, max_tokens=1024) -> ProviderResponse:
        self.complete_calls.append(messages)
        if self.error is not None:
            raise self.error
        return ProviderResponse(text=self.text, model="qwen3-vl:2b", raw={})

    def unload(self) -> None:
        self.unload_calls += 1


def fake_paddleocr_module(markdown: str = "Extracted via PaddleOCR", calls: list | None = None):
    module = types.ModuleType("paddleocr")

    class _Page:
        def __init__(self):
            self.markdown = markdown

    class _PaddleOCRVL:
        def __init__(self, pipeline_version="v1"):
            self.pipeline_version = pipeline_version

        def predict(self, path):
            if calls is not None:
                calls.append(path)
            return [_Page()]

    module.PaddleOCRVL = _PaddleOCRVL
    return module


class IsTextFileTests(unittest.TestCase):
    def test_known_text_extensions(self):
        for name in ("a.txt", "a.md", "a.json", "A.TXT"):
            with self.subTest(name=name):
                self.assertTrue(is_text_file(Path(name)))

    def test_non_text_extensions(self):
        for name in ("a.png", "a.pdf", "a.jpg"):
            with self.subTest(name=name):
                self.assertFalse(is_text_file(Path(name)))


class LoadTextFromFileTests(unittest.TestCase):
    def test_text_file_read_directly(self):
        text = load_text_from_file(FIXTURES / "invoice.txt")
        self.assertEqual(text, (FIXTURES / "invoice.txt").read_text(encoding="utf-8"))

    def test_md_and_json_also_skip_ocr(self):
        with tempfile.TemporaryDirectory() as tmp:
            for suffix, content in ((".md", "# Title\nBody"), (".json", '{"a": 1}')):
                path = Path(tmp) / f"file{suffix}"
                path.write_text(content, encoding="utf-8")
                with self.subTest(suffix=suffix):
                    self.assertEqual(load_text_from_file(path), content)

    def test_image_uses_paddleocr_when_available(self):
        predict_calls: list = []
        fake_module = fake_paddleocr_module("Extracted via PaddleOCR", calls=predict_calls)
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "page.png"
            image_path.write_bytes(b"not a real png, paddleocr is faked")
            with mock.patch.dict(sys.modules, {"paddleocr": fake_module}):
                text = load_text_from_file(image_path, vl_provider=FakeVlProvider("should not be used"))

        self.assertEqual(text, "Extracted via PaddleOCR")
        self.assertEqual(len(predict_calls), 1)

    def test_image_falls_back_to_ollama_when_paddleocr_missing(self):
        sys.modules.pop("paddleocr", None)  # genuinely not installed in this venv
        fake_vl = FakeVlProvider("Extracted via qwen3-vl")

        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "page.png"
            image_path.write_bytes(b"fake image bytes")
            text = load_text_from_file(image_path, vl_provider=fake_vl)

        self.assertEqual(text, "Extracted via qwen3-vl")
        self.assertEqual(len(fake_vl.complete_calls), 1)
        self.assertIn("images", fake_vl.complete_calls[0][0])
        self.assertEqual(fake_vl.unload_calls, 1)  # unloaded before returning to the caller

    def test_ocr_error_when_both_paddleocr_and_ollama_fail(self):
        sys.modules.pop("paddleocr", None)
        fake_vl = FakeVlProvider(error=ConnectionError("ollama not running"))

        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "page.png"
            image_path.write_bytes(b"fake image bytes")
            with self.assertRaises(OcrError) as ctx:
                load_text_from_file(image_path, vl_provider=fake_vl)

        self.assertEqual(ctx.exception.code, "ocr_failed")
        self.assertEqual(fake_vl.unload_calls, 1)  # still unloaded even though extraction failed

    def test_pdf_without_pymupdf_raises_clear_error(self):
        sys.modules.pop("fitz", None)  # PyMuPDF genuinely not installed
        with self.assertRaises(OcrError) as ctx:
            load_text_from_file(Path("does-not-need-to-exist.pdf"))
        self.assertEqual(ctx.exception.code, "pdf_render_unavailable")


if __name__ == "__main__":
    unittest.main()
