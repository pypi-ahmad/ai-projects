"""Token counting consistent with the embed model's tokenizer, with a documented
approximation fallback when that tokenizer can't be loaded (e.g. no network access
to Hugging Face Hub the first time, or the `tokenizers` package is unavailable).
"""

import logging

logger = logging.getLogger(__name__)

# Must match config.ALLOWED_OLLAMA_MODELS' dense-embed default (qwen3-embedding:0.6b).
EMBED_MODEL_HF_REPO = "Qwen/Qwen3-Embedding-0.6B"

# APPROXIMATION ONLY, not the embed model's real tokenizer: ~4 characters per
# token is a commonly cited rough average for English text under a BPE
# tokenizer. Used only when the real tokenizer can't be loaded.
_APPROX_CHARS_PER_TOKEN = 4

_tokenizer = None
_load_attempted = False


def _get_tokenizer():
    global _tokenizer, _load_attempted
    if _load_attempted:
        return _tokenizer
    _load_attempted = True
    try:
        from tokenizers import Tokenizer

        _tokenizer = Tokenizer.from_pretrained(EMBED_MODEL_HF_REPO)
        logger.info("using %s tokenizer for token counts", EMBED_MODEL_HF_REPO)
    except Exception:
        logger.warning(
            "could not load the %s tokenizer; falling back to a ~%d "
            "chars/token APPROXIMATION for token counts",
            EMBED_MODEL_HF_REPO,
            _APPROX_CHARS_PER_TOKEN,
        )
        _tokenizer = None
    return _tokenizer


def count_tokens(text: str) -> int:
    tokenizer = _get_tokenizer()
    if tokenizer is not None:
        return len(tokenizer.encode(text).ids)
    # Approximation -- see _APPROX_CHARS_PER_TOKEN above.
    return max(1, len(text) // _APPROX_CHARS_PER_TOKEN)
