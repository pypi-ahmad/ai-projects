"""OCR calls through Ollama: AuditAid/PaddleOCR-VL-1.6-0.9B first, qwen3-vl:2b on failure."""

import logging

import ollama

logger = logging.getLogger(__name__)

PRIMARY_OCR_MODEL = "AuditAid/PaddleOCR-VL-1.6-0.9B"
FALLBACK_OCR_MODEL = "qwen3-vl:2b"

# PaddleOCR-VL's documented element-level recognition prompt (see SPEC.md).
_PRIMARY_PROMPT = "OCR:"
# qwen3-vl is a general vision-language model, not tuned to PaddleOCR-VL's prompt
# convention, so it needs an explicit instruction instead.
_FALLBACK_PROMPT = (
    "Extract all text from this image, verbatim, preserving line breaks and reading order."
)


def ocr_image(image_bytes: bytes, client: ollama.Client) -> tuple[str, float | None, str]:
    """Returns (text, confidence, model_used).

    confidence is always None today: a plain Ollama chat call carries no per-token
    or per-region confidence signal for either model. The field is kept so a real
    confidence source can be wired in later without a schema change.
    """
    try:
        response = client.chat(
            model=PRIMARY_OCR_MODEL,
            messages=[{"role": "user", "content": _PRIMARY_PROMPT, "images": [image_bytes]}],
        )
        return response.message.content or "", None, PRIMARY_OCR_MODEL
    except Exception:
        logger.warning("%s failed, falling back to %s", PRIMARY_OCR_MODEL, FALLBACK_OCR_MODEL)
        response = client.chat(
            model=FALLBACK_OCR_MODEL,
            messages=[{"role": "user", "content": _FALLBACK_PROMPT, "images": [image_bytes]}],
        )
        return response.message.content or "", None, FALLBACK_OCR_MODEL


def unload_model(client: ollama.Client, model: str) -> None:
    try:
        client.generate(model=model, prompt="", keep_alive=0)
    except Exception:
        logger.warning("failed to unload %s", model)
