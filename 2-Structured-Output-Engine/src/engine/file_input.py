"""Optional extract-from-file: image or scanned PDF page -> text, then the
same text pipeline (Pipeline.run doesn't know or care where the text came
from). Plain text/md/json files skip OCR entirely.

OCR path: AuditAid/PaddleOCR-VL-1.6-0.9B (primary) -> qwen3-vl:2b via Ollama
(fallback, `images` field on a /api/chat message — verified against
docs.ollama.com, no code changes needed to OllamaProvider since messages
pass through as plain dicts). The primary pulls in `paddleocr` +
`paddlepaddle`, which can be painful to install on native Windows
(PaddlePaddle's Windows GPU wheel support is limited) — its import is
deferred to first use and isolated here so a missing/broken install falls
back to the Ollama path instead of breaking anything else. PDF rendering
(`PyMuPDF`) is lazy-imported the same way, for the same reason; neither is
a hard dependency of this project (see docs/RUNBOOK.md to opt in).

VRAM discipline (NOTES.md, 8GB GPU): the VL/OCR model is always unloaded
before this function returns, so the caller's subsequent generate-model
load isn't fighting it for VRAM.
"""

from __future__ import annotations

import base64
import tempfile
from pathlib import Path

from providers.base import Provider
from providers.ollama_provider import OllamaProvider

TEXT_EXTENSIONS = {".txt", ".md", ".json"}
PDF_EXTENSIONS = {".pdf"}

PADDLEOCR_MODEL = "AuditAid/PaddleOCR-VL-1.6-0.9B"
FALLBACK_VL_MODEL = "qwen3-vl:2b"

_VL_PROMPT = "Extract all text from this image, verbatim, in reading order. Return only the extracted text."


class OcrError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def is_text_file(path: Path) -> bool:
    return path.suffix.lower() in TEXT_EXTENSIONS


def load_text_from_file(path: Path, *, vl_provider: Provider | None = None) -> str:
    """Read a text file directly, or OCR an image/scanned PDF page."""
    if is_text_file(path):
        return path.read_text(encoding="utf-8")

    image_bytes = _page_to_image_bytes(path)

    try:
        return _extract_with_paddleocr(image_bytes)
    except OcrError:
        return _extract_with_ollama_vl(image_bytes, provider=vl_provider)


def _page_to_image_bytes(path: Path) -> bytes:
    if path.suffix.lower() not in PDF_EXTENSIONS:
        return path.read_bytes()

    try:
        import fitz  # PyMuPDF — lazy import, not a hard dependency (see module docstring)
    except ImportError as exc:
        raise OcrError(
            "pdf_render_unavailable",
            f"PyMuPDF is not installed ({exc}). Install it with `uv add pymupdf` to process PDF files.",
        ) from exc

    with fitz.open(path) as doc:
        return doc.load_page(0).get_pixmap().tobytes("png")  # "a scanned PDF page": first page only


def _extract_with_paddleocr(image_bytes: bytes) -> str:
    try:
        from paddleocr import PaddleOCRVL
    except ImportError as exc:
        raise OcrError(
            "ocr_unavailable",
            f"paddleocr is not installed ({exc}); falling back to {FALLBACK_VL_MODEL} via Ollama.",
        ) from exc

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(image_bytes)
            tmp_path = tmp.name
        pipeline = PaddleOCRVL(pipeline_version="v1")
        pages = list(pipeline.predict(tmp_path))
        text = "\n".join(getattr(page, "markdown", None) or str(page) for page in pages).strip()
        if not text:
            raise OcrError("ocr_empty_result", "PaddleOCR returned no text")
        return text
    except OcrError:
        raise
    except Exception as exc:  # model load / inference failure -> fall back, don't crash the pipeline
        raise OcrError("ocr_failed", f"PaddleOCR failed: {exc}") from exc
    finally:
        if tmp_path is not None:
            Path(tmp_path).unlink(missing_ok=True)


def _extract_with_ollama_vl(image_bytes: bytes, *, provider: Provider | None = None) -> str:
    vl_provider = provider or OllamaProvider(FALLBACK_VL_MODEL)
    messages = [
        {
            "role": "user",
            "content": _VL_PROMPT,
            "images": [base64.b64encode(image_bytes).decode("ascii")],
        }
    ]
    try:
        response = vl_provider.complete(messages, temperature=0.0)
    except Exception as exc:  # provider boundary: network/auth/timeout/etc all degrade the same way
        raise OcrError("ocr_failed", f"{FALLBACK_VL_MODEL} via Ollama failed: {exc}") from exc
    finally:
        if hasattr(vl_provider, "unload"):
            try:
                vl_provider.unload()
            except Exception:
                pass  # best-effort — a failed unload shouldn't mask a successful extraction
    if not response.text.strip():
        raise OcrError("ocr_empty_result", f"{FALLBACK_VL_MODEL} returned no text")
    return response.text
