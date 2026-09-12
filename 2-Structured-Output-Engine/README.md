# Structured Output Engine

Give it text and a Pydantic schema; it gives back a validated instance of
that schema or a typed failure. It never hands an app raw free text when a
schema was requested; invalid output is retried, then repaired (with a
different, usually cheaper model), before the pipeline gives up.

**Status: Phase 8; CLI and Streamlit UI, both working end to end.**
`src/engine/pipeline.py` is the actual product: text + schema → provider →
JSON extraction → Pydantic validation → retry → cross-model repair →
graceful fallback → `StructuredResult`. `--file`/file upload (optional)
adds OCR for images/scanned PDFs ahead of the same pipeline. The legacy,
disconnected `StructuredOutputEngine` (`engine/core.py`) was deleted in
Phase 8; `Pipeline` was always the real path. See [ROADMAP.md](ROADMAP.md)
for what's still open (a hosted-provider eval comparison is blocked on a
valid `GOOGLE_API_KEY`/`OPENAI_API_KEY`/`AGNES_API_KEY`; packaging polish).

## 30-second demo

1. `run.cmd` (or `uv run python -m streamlit run src/ui/app.py`).
2. In the sidebar: provider `ollama`, model `granite4.1:3b`, schema `invoice_draft`.
3. Paste a messy paragraph into the text area, e.g.:
   > *"ok so acme sent over the bill again, its in euros this time i think, they charged us for like 3 things -- consulting hours (5 of them at 100 each so 500), a licensing fee (200 flat), and some travel reimbursement (75) -- total should come out to 775, this was from the 3rd of feb 2026"*
4. Click **Run**; a validated `InvoiceDraft` JSON appears, with the errors table and attempt timeline empty (or populated, if it needed a retry).

## Run (Windows-native)

No WSL2, no Docker; a plain Windows Python environment via
[uv](https://docs.astral.sh/uv/). Requires a running local
[Ollama](https://ollama.com) instance for the local provider and default
repair model.

```
uv sync
uv run python -m src.engine --schema invoice --text-file tests/fixtures/invoice.txt --provider ollama --model granite4.1:3b
```

Or `--file path/to/scan.png` instead of `--text-file` to OCR an image or
scanned PDF page first (optional; see Limitations and `docs/RUNBOOK.md`
"Extract from file").

**Or just double-click `run.cmd`**; it creates a `.venv`, `pip install`s
`requirements.txt`, copies `.env.example` to `.env` if missing, warns (but
doesn't fail) if Ollama isn't reachable, and launches the Streamlit UI. It
targets a plain `python`+`pip` install, not `uv`; verified working from a
clean environment. See `docs/RUNBOOK.md` for every CLI flag.

## Providers

All four implement the shared `complete(messages, json_schema, temperature,
max_tokens) -> ProviderResponse` interface (`src/providers/`) over raw HTTP.

| Provider | Models | Structured output |
|---|---|---|
| Ollama (local) | `granite4.1:3b`, `qwen3.5:0.8b`, ... (allowlist in `ollama_provider.py`) | `format=<json schema>` if the server is ≥0.5.0 (detected via `/api/version`), else schema embedded in the prompt |
| Agnes AI | `agnes-2.5-flash` | Not documented by Agnes; always prompt-embedded (verified against their docs, not assumed) |
| OpenAI-compatible | `gpt-5.6-luna`, `gpt-5.6-terra` | `response_format: json_schema` |
| Gemini | `gemini-3.5-flash-lite`, `gemini-3.7-flash` | `responseJsonSchema` |

`Pipeline`'s repair stage defaults to a **local Ollama `qwen3.5:0.8b`**
regardless of which provider the initial pass used; pass `--pin-provider`
(CLI) or `pin_provider=True` (`Pipeline(...)`) to repair with the same
provider/model instead. All four are selectable in the sidebar of
`src/ui/app.py`.

## Allowed local models

Fixed allowlist (see [NOTES.md](NOTES.md)); no other local model is used:

- `granite4.1:3b`
- `qwen3.5:2b`
- `qwen3.5:0.8b`
- `qwen3-vl:2b`
- `qwen3-embedding:0.6b`
- `qwen3-embedding:4b`
- `translategemma:4b`
- `AuditAid/PaddleOCR-VL-1.6-0.9B`

On an 8GB GPU, only one heavy model is loaded at a time;
`OllamaProvider.unload(model)` (`keep_alive=0`) frees VRAM before the next
stage loads another. `Pipeline` calls it automatically when a repair-stage
attempt switches to a different provider (Phase 8); `--file`'s OCR/VL model
is likewise unloaded before the generate model loads (see
`docs/RUNBOOK.md` "VRAM unload order"). Nothing unloads the model a run
ultimately ends on.

## Repo map

```
src/engine/     Pipeline (the real product), CLI entry point, file/OCR input, result envelope
src/providers/  Ollama / Agnes / OpenAI-compatible / Gemini adapters, shared HTTP retry + error codes
src/schemas/    Built-in Pydantic schemas, registry, JSON-Schema-to-Pydantic converter
src/eval/       Eval harness — used by the Streamlit UI's Eval tab and directly
src/ui/         Streamlit app (run.cmd's entry point)
tests/          unittest modules; tests/fixtures (sample invoice text + image); tests/eval (eval cases)
docs/           ARCHITECTURE.md, TECHNICAL.md, RUNBOOK.md, EVAL.md, SCHEMAS.md
```

No `docs/CONTRIBUTING.md`; solo project, no CI, no external contribution
workflow to document.

## Tests

Stdlib `unittest`, no pytest dependency:

```
uv run python -m unittest discover -s tests -v
```

## Example

```python
from engine.pipeline import Pipeline
from providers import OllamaProvider
from schemas import registry

schema = registry.get("contact_record")
pipeline = Pipeline(OllamaProvider("granite4.1:3b"), "granite4.1:3b")
result = pipeline.run("Reach Ada Lovelace at ada@example.com.", schema)
```

Text in:

```
Reach Ada Lovelace at ada@example.com.
```

Validated JSON out (`result.ok is True`, `result.data` is a real
`ContactRecord` instance; shown here as JSON for illustration):

```json
{"name": "Ada Lovelace", "email": "ada@example.com", "phone": null, "tags": []}
```

On failure, `result.ok` is `False`, `result.errors` is a list of
`ValidationIssue(loc, msg, type)`, and `result.data` depends on
`fallback=`: `"partial"` (default) keeps whatever fields validated and
fills only non-required ones from schema defaults, `"empty"` gives `None`,
`"raise"` (CLI `--strict`) raises `PipelineFailure`; caught at the CLI's
own top level, never left as a raw traceback. Never raw text treated as
valid.

## Limitations

- No fallback *across providers* mid-pipeline; repair can switch models
  (see Providers above) but a hard outage on both the primary and repair
  provider still ends in `ok=False`.
- The UI's "paste JSON Schema" option is a best-effort JSON-Schema-to-Pydantic
  converter (`schemas/dynamic.py`); it doesn't support `$ref`/`$defs`/`anyOf`/`oneOf`/`allOf`.
- OCR (`--file`/file upload on an image/PDF) is optional. Its Ollama-VL
  fallback (`qwen3-vl:2b`) has been verified live end-to-end against a
  synthetic invoice image (Phase 8); PaddleOCR itself, and any real
  scanned document, remain unverified. PaddleOCR (`paddleocr`/`paddlepaddle`)
  and PDF rasterization (`PyMuPDF`) are not installed by default; the code
  degrades to plain-text-only behavior (a clear error on `--file` with an
  image/PDF, everything else unaffected) until you `uv add` them; see
  `docs/RUNBOOK.md`.
- No RAG, no fine-tuning, no Docker; out of scope for this project.
- `.env` values are not auto-loaded yet; env vars must be set in the
  OS/shell environment, or passed as explicit provider constructor
  arguments (see `docs/RUNBOOK.md`).
- `--file`'s OCR/VL model is unloaded before the generate model loads (see
  `docs/RUNBOOK.md` "VRAM unload order"). `Pipeline` also unloads the
  outgoing provider's model when a repair-stage switch changes provider
  (Phase 8); but nothing unloads the final model a run ends on, so a long
  CLI/UI session against Ollama will keep the last-used one resident.

<p align="center">Made with ❤️ by Ahmad Mujtaba</p>
