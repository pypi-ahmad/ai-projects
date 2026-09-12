# Technical Reference

## Tokenizer

**`tiktoken` — `cl100k_base` encoding.** Loaded once in `src/blocks/tokenizer.py`:

```python
class TokenCounter:
    def __init__(self, encoding="cl100k_base"):
        self._enc = tiktoken.get_encoding(encoding)
    def count(self, text: str) -> int:
        return len(self._enc.encode(text))
```

Rationale:
- Installs on Windows with no build tools or GPU.
- `cl100k_base` is a close approximation for Claude and GPT-4 models; counts run 5–10% high on average, which is conservative (safer than under-counting).
- Subsequent calls are in-process (~1 µs per short string).

To switch encodings, change the `encoding` argument in `TokenCounter.__init__`.
The rest of the pipeline is encoding-agnostic.

## Block model

`src/blocks/models.py` — `ContextBlock`:

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Unique identifier (uuid4.hex by default) |
| `family` | `"memory" \| "docs" \| "tools" \| "system" \| "user"` | Routing family |
| `text` | `str` | Block content |
| `priority` | `int` | Higher = kept first (0–100 convention) |
| `token_count` | `Optional[int]` | Populated by `TokenCounter.count_block()` |
| `droppable` | `bool` | May be omitted to fit budget (default `True`) |
| `compressible` | `bool` | May be summarised before dropping (default `False`) |
| `source` | `Optional[str]` | File path, tool name, or memory key |

`system` and `user` family blocks are **never dropped** by the allocator — they bypass the priority pack loop entirely.

**This service does not retrieve documents.** The caller selects candidate blocks (from a vector
store, file system, or any other source) and passes them as `ContextBlock` objects. The assembler
only decides which ones fit.

## Block priorities

Priorities are integers; higher = kept first. Suggested defaults:

| Block type | Priority range |
|------------|----------------|
| System prompt | 100 |
| Tool schemas (active) | 80–90 |
| Recent memory turns | 70–80 |
| High-relevance doc chunks | 50–70 |
| Older memory / lower-relevance docs | 10–50 |
| Tool results (verbose) | 20–50 |

These are conventions; callers override freely.

## Allocation algorithm (3-pass)

Implemented in `src/budget/allocator.py`:

```
usable = context_window − output_reserve − system_reserve − user_message_tokens

Pass A  force-keep the highest-priority block per non-empty packable family
Pass B  fill remaining blocks within each family's soft cap
Pass C  borrow: remaining leftover blocks consume any cross-family surplus
        if compressible and space remains → CompressJob
        else → DropRecord(reason=OVER_FAMILY_CAP | OVER_WINDOW | ZERO_PRIORITY)
```

`system` and `user` blocks are placed into `kept` before Pass A and do not consume the usable budget counter.

## Compression pipeline

`src/compress/compressor.py` — `run_compress_jobs(plan, provider_fn, unload_after=True)`:

1. For each `CompressJob` call `compress_one(job, provider_fn)`.
2. `provider_fn(text, target_tokens, tiny, must_keep) → str | None`.
3. Default chain: `providers.compress()` — Ollama → Agnes AI → OpenAI-compat → Gemini.
4. `tiny=True` when `block.token_count < 400` (prefers `qwen3.5:0.8b`).

| Outcome | Condition | Result |
|---------|-----------|--------|
| `OK` | Provider returned text shorter than target | Block moved to `kept` |
| `TRIMMED` | Still over target; hard-trimmed at last sentence boundary | Block moved to `kept` |
| `COMPRESS_FAILED` | Provider returned text ≥ original length | Block moved to `dropped` |
| `COMPRESS_UNAVAILABLE` | All providers returned `None` | Block moved to `dropped` |

Compression is **optional and offline-safe** — packing always returns a valid result with no providers configured.

## Compression prompt (in `providers.py`)

```
Shorten the following to under {target_tokens} tokens.
Preserve all entities, numbers, and source tags (e.g. [D1], [T1]).
Do not add new facts. Reply with the shortened text only.
[If must_keep set:] You must keep: {must_keep}.

{text}
```

## Message layout (packer output)

```
[{"role": "system", "content":
    {system blocks}

    ## Memory
    {memory blocks}

    ## Retrieved Documents
    [D1] {doc block 1}
    [D2] {doc block 2}

    ## Available Tools
    [T1] {tool block 1}
},
 {"role": "user", "content": {user_message}}]
```

## Windows-specific notes

- All paths use `pathlib.Path` or backward-compatible separators; no POSIX-only calls.
- Ollama runs natively on Windows; `OLLAMA_HOST` defaults to `http://localhost:11434`.
- `run.cmd` uses `uv run` — no manual venv activation required.
- No POSIX signals, `fork()`, or `/dev/null` in any code path.
