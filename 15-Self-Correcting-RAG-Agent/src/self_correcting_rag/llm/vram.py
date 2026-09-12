"""VRAM discipline for Ollama: only one heavy model resident at a time.

The RTX 4060 8GB has no headroom to keep multiple Ollama models loaded
together. Call unload_all() before loading the next stage's model, e.g.
between embed -> generate -> OCR.

Nothing in this module calls unload_all() automatically -- callers (index/pipeline.py,
retrieve/pipeline.py) must call it themselves after an embed batch. If a new caller starts
loading a different Ollama model without doing so, both models can end up resident.
"""

import ollama


def loaded_models(client: ollama.Client) -> list[str]:
    return [m.model for m in client.ps().models if m.model]


def unload_all(client: ollama.Client) -> list[str]:
    """Evict every currently resident model. keep_alive=0 unloads immediately
    after the (otherwise empty) request completes. Returns the names unloaded.
    """
    models = loaded_models(client)
    for model in models:
        client.generate(model=model, keep_alive=0)
    return models
