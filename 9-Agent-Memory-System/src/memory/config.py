"""Paths, allowed models, and provider settings shared by every memory store.

Constants only -- the only I/O this module performs is ensure_data_dirs().
Every other module in src/memory/ imports paths/model names from here
rather than hardcoding one a second time; must not become a place that
calls Ollama, SQLite, or Qdrant itself.

Next: src/memory/working.py -- the simplest store, and the template every
other store's Pydantic-model shape follows.
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data" / "memory"
QDRANT_PATH = DATA_DIR / "qdrant"
INDEX_META_PATH = DATA_DIR / "index_meta.json"
SQLITE_PATH = DATA_DIR / "memory.db"
WORKING_SNAPSHOT_PATH = DATA_DIR / "working.json"
MEMORY_YAML_PATH = PROJECT_ROOT / "config" / "memory.yaml"

FACTS_COLLECTION = "facts"

# Working memory token budget and counting approach.
WORKING_TOKEN_CAP = 1500
# Same approach as the Context Assembly Service project (3-Context-Assembly-Service):
# tiktoken cl100k_base. Exact for OpenAI-family models; for the Ollama GGUF models
# used here (granite4.1, qwen3.5) it runs ~5-10% high, which is conservative.
TOKEN_ENCODING = "cl100k_base"


def ensure_data_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


# Only these are pulled locally (`ollama list`). Never request another name.
ALLOWED_OLLAMA_MODELS = frozenset(
    {
        "granite4.1:3b",
        "qwen3.5:2b",
        "qwen3.5:0.8b",
        "qwen3-vl:2b",
        "qwen3-embedding:0.6b",
        "qwen3-embedding:4b",
        "translategemma:4b",
        "AuditAid/PaddleOCR-VL-1.6-0.9B",
    }
)

EMBED_MODEL = "qwen3-embedding:0.6b"
COMPRESS_MODEL_DEFAULT = "qwen3.5:0.8b"
COMPRESS_MODEL_FALLBACK = "qwen3.5:2b"
DEBUG_CHAT_MODEL = "granite4.1:3b"

# RTX 4060 8GB: embed and compress models never load at once (see providers.py).
GPU_VRAM_MB = 8188

# Non-Ollama providers for compress/debug (Phase 8, still unbuilt -- see
# src/memory/providers.py; compress.py/semantic.py only call Ollama).
# Exact env var names per
# the user-env-variable skill catalog; never substitute or rename these.
AGNESAI_BASE_URL = "https://apihub.agnes-ai.com/v1"
AGNESAI_MODEL = "agnes-2.5-flash"
OPENAI_COMPATIBLE_MODELS = ("gpt-5.6-luna", "gpt-5.6-terra")
GEMINI_MODELS = ("gemini-3.5-flash-lite", "gemini-3.7-flash")


def available_providers() -> dict[str, bool]:
    """Which non-Ollama providers have credentials in the current process env."""
    return {
        "agnes": bool(os.environ.get("AGNESAI_API_KEY")),
        "openai_compatible": bool(os.environ.get("OPENAI_API_KEY")),
        "gemini": bool(os.environ.get("GOOGLE_API_KEY")),
    }
