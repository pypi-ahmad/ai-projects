# Per-vendor complete() adapters live in this package's other modules
# (ollama.py, agnes.py, openai_compat.py, gemini.py) but are imported lazily
# by route/executor.py, not re-exported here — this __init__ only exposes the
# availability check used by route/router.py at decision time.
from .availability import default_available

__all__ = ["default_available"]
