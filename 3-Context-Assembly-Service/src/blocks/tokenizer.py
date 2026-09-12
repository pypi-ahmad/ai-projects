"""
TokenCounter — tiktoken-based token counter with per-block caching.

Encoding: cl100k_base (GPT-4 BPE).
Approximation note: counts are exact for OpenAI-family models. For Ollama GGUF
quantized models (granite4.1, qwen3.5) the actual tokenizer differs; cl100k_base
typically runs 5-10% high, which is conservative (safer than under-counting for
budget enforcement).

See src/budget/allocator.py, which calls count_request() before allocating.
"""
from __future__ import annotations
import tiktoken
from src.blocks.models import ContextBlock, ContextRequest


class TokenCounter:
    def __init__(self, encoding: str = "cl100k_base") -> None:
        self._enc = tiktoken.get_encoding(encoding)
        self.encoding = encoding

    def count(self, text: str) -> int:
        """Token count for a string. Empty string → 0. Deterministic."""
        return len(self._enc.encode(text))

    def count_block(self, block: ContextBlock, force: bool = False) -> int:
        """
        Return token count for block.text, caching the result on block.token_count.
        Pass force=True to recount after block.text changes.
        """
        if block.token_count is None or force:
            block.token_count = self.count(block.text)
        return block.token_count

    def count_request(self, request: ContextRequest) -> None:
        """Count tokens for every block in the request (in-place). Skips already-counted blocks."""
        for block in request.blocks:
            self.count_block(block)
