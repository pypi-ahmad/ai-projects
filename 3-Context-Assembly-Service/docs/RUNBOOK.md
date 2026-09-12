# Runbook

## Prerequisites

- Python 3.11+
- `uv` — `winget install astral-sh.uv` or see https://docs.astral.sh/uv/
- No GPU required for core packing path

## Setup

```cmd
cd D:\ai-projects\3-Context-Assembly-Service
uv sync
```

## Run the UI

```cmd
run.cmd
```

`run.cmd` creates the venv if absent, runs `uv sync`, loads `.env`, warns if Ollama is
unreachable, then starts Streamlit at `http://localhost:8501`.

## Run tests (offline — no model, no keys required)

```cmd
uv run pytest tests/test_blocks.py tests/test_budget.py tests/test_packer.py tests/test_compress.py test_context_assembly.py
```

Expected: **80 passed**.

## Run eval suite

```cmd
uv run python tests/eval/run_eval.py
```

Expected: **6/6 passed**, `overflow_count: 0`.

## CLI packer

```cmd
uv run python -m src.assembly ^
    --request tests/fixtures/sample_request.json ^
    --policy  balanced ^
    --out     out/pack.json
```

## Environment variables

Create a `.env` file in the project root with any of the variables listed below. All are optional — packing works with none set.

| Variable | Purpose | Required |
|----------|---------|----------|
| `OLLAMA_HOST` | Ollama base URL | No (default `http://localhost:11434`) |
| `AGNES_API_KEY` | Agnes AI key | No |
| `OPENAI_API_KEY` | OpenAI-compatible key | No |
| `OPENAI_BASE_URL` | OpenAI-compatible base URL | No (required if `OPENAI_API_KEY` is set) |
| `GOOGLE_API_KEY` | Gemini key | No |

## Ollama setup (compression only)

Ollama is only needed when a block has `compressible=True` and compress mode is `auto` (UI) or
`run_compress_jobs()` is called explicitly.

```cmd
REM Install from https://ollama.com (Windows native installer)
ollama pull qwen3.5:2b
REM Optional smaller model for blocks < 400 tokens:
ollama pull qwen3.5:0.8b
```

Never load two 3B+ models simultaneously — RTX 4060 8 GB ceiling.

## Verify Ollama is detected

```python
from providers import ollama_available_models
print(ollama_available_models())   # lists installed models; [] if Ollama unreachable
```

## Provider chain (compression only)

When `run_compress_jobs()` is called, providers are tried in this order until one succeeds:

1. Ollama — `qwen3.5:2b` (blocks ≥ 400 tokens) or `qwen3.5:0.8b` (blocks < 400 tokens)
2. Agnes AI — `AGNES_API_KEY`
3. OpenAI-compatible — `OPENAI_API_KEY` + `OPENAI_BASE_URL`
4. Gemini — `GOOGLE_API_KEY`

If all providers fail or are unconfigured, the block is dropped with reason
`COMPRESS_UNAVAILABLE`. Packing still completes and returns a valid result.

## Known gaps

- `src/eval/__init__.py` and `src/providers/__init__.py` are empty stubs. Eval logic lives in
  `tests/eval/run_eval.py`; provider logic lives in the root-level `providers.py`.
- Compression prompt is intentionally terse; no fine-tuning or quality evaluation of summaries
  beyond the TRIMMED / COMPRESS_FAILED safeguards.
