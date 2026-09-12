"""Language detection and translategemma:4b translation."""

import logging

import ollama
from langdetect import LangDetectException, detect

logger = logging.getLogger(__name__)

TRANSLATE_MODEL = "translategemma:4b"

# ponytail: covers common cases; unknown codes fall back to using the code itself
# as the name in the prompt, which TranslateGemma should still understand (its
# supported-languages table is keyed by these same ISO codes). Extend if a real
# corpus surfaces a language whose name matters for translation quality.
_LANG_NAMES = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "nl": "Dutch",
    "ru": "Russian",
    "zh-cn": "Chinese",
    "zh-tw": "Chinese",
    "ja": "Japanese",
    "ko": "Korean",
    "ar": "Arabic",
    "hi": "Hindi",
}


def detect_lang(text: str) -> str:
    if not text.strip():
        return "unknown"
    try:
        return detect(text)
    except LangDetectException:
        return "unknown"


def _lang_name(code: str) -> str:
    return _LANG_NAMES.get(code, code)


def translate_pages(
    pages: list[str], source_lang: str, target_lang: str, client: ollama.Client
) -> list[str]:
    source_name = _lang_name(source_lang)
    target_name = _lang_name(target_lang)
    translated = []
    for page_text in pages:
        if not page_text.strip():
            translated.append("")
            continue
        prompt = (
            f"You are a professional {source_name} ({source_lang}) to {target_name} "
            f"({target_lang}) translator. Your goal is to accurately convey the meaning "
            f"and nuances of the original {source_name} text while adhering to "
            f"{target_name} grammar, vocabulary, and cultural sensitivities.\n"
            f"Produce only the {target_name} translation, without any additional "
            f"explanations or commentary. Please translate the following {source_name} "
            f"text into {target_name}:\n\n\n{page_text}"
        )
        response = client.chat(
            model=TRANSLATE_MODEL, messages=[{"role": "user", "content": prompt}]
        )
        translated.append(response.message.content or "")
    return translated
