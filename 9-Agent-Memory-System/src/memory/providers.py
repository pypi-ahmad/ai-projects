"""LLM/embedding provider abstraction.

Ollama default, with Agnes AI / OpenAI-compatible / Gemini fallback for
compress and debug chat. Owns the embed<->compress unload sequencing on the
8 GB 4060 (`keep_alive=0` before switching models).

compress.py and semantic.py both call Ollama directly instead (no
fallback chain, no unload sequencing yet). This module is still just the
multi-provider abstraction, not yet needed.

Must not: be imported expecting a working implementation -- this file
defines no classes or functions yet, only this docstring.

Next: src/memory/compress.py -- the direct-Ollama calls this would replace.

Phase 8.
"""
