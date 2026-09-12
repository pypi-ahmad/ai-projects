# Runbook

## Environment variables

Copy `.env.example` to `.env` and fill in what you use. **`.env` is not
auto-loaded yet** (no `python-dotenv` wiring); until then, export these in
your shell/OS environment, or pass them as explicit constructor arguments
(every provider accepts the value directly, falling back to the env var
only when the argument is omitted).

| Variable | Used by | Status |
|---|---|---|
| `OLLAMA_HOST` | `OllamaProvider` | Read directly if `host=` isn't passed. Default `http://127.0.0.1:11434` if unset. |
| `AGNES_API_KEY` | `AgnesProvider` | Read directly if `api_key=` isn't passed. Raises `ProviderError("missing_api_key", ...)` if both are unset. |
| `OPENAI_API_KEY` | `OpenAICompatibleProvider` | Same pattern. |
| `OPENAI_BASE_URL` | `OpenAICompatibleProvider` | Same pattern (`ProviderError("missing_base_url", ...)` if unset). |
| `GOOGLE_API_KEY` | `GeminiProvider` | Same pattern. |

All four providers work end to end through `engine.pipeline.Pipeline` (see
CLI below and README's Example).

## CLI

```
uv run python -m src.engine --schema invoice --text-file tests/fixtures/invoice.txt --provider ollama --model granite4.1:3b
```

Run from the project root. `--schema` accepts a full registry name
(`invoice_draft`) or any unambiguous prefix (`invoice`). Other flags:
`--text` (inline, instead of `--text-file`), `--file` (text/md/json read
directly, or an image/scanned PDF page OCR'd first; see "Extract from
file" below), `--repair-provider` / `--repair-model` (default: local
Ollama `qwen3.5:0.8b`), `--pin-provider` (repair with the same
provider/model instead of switching), `--max-attempts` (default 3),
`--fallback partial|empty|raise` / `--strict` (shortcut for `--fallback
raise`), `--temperature`, `--max-tokens`, `--log-level`. Exit code 0 on
`ok=True`, 1 otherwise (including an unknown `--schema` or a failed OCR
extraction); never an uncaught traceback, even with `--strict`.

## Extract from file (`--file`, optional)

```
uv run python -m src.engine --schema invoice --file path/to/scan.png --provider ollama --model granite4.1:3b
```

`engine.file_input.load_text_from_file` decides by extension:

- `.txt` / `.md` / `.json` → read directly, no OCR, no extra dependency.
- Anything else (image, or `.pdf`; first page only) → OCR, then the same
  text pipeline as `--text`/`--text-file`.

OCR tries, in order:

1. **PaddleOCR** (`AuditAid/PaddleOCR-VL-1.6-0.9B`); **not installed by
   default.** Requires `paddlepaddle` + `paddleocr[doc-parser]`, which can
   be genuinely painful on native Windows (PaddlePaddle's Windows GPU wheel
   support is limited; CPU-only is more reliable but slower). To opt in:
   ```
   uv add paddlepaddle  # or paddlepaddle-gpu per paddlepaddle.org.cn's install matrix for your CUDA version
   uv add "paddleocr[doc-parser]"
   ```
   If the import fails for any reason (not installed, broken install,
   model-load error, inference error), this is caught and step 2 runs
   instead; nothing else in the project breaks.
2. **`qwen3-vl:2b` via Ollama**; no extra dependency, just another
   `/api/chat` call with the image base64-encoded in the message's
   `images` field. Pull it first: `ollama pull qwen3-vl:2b`.

**PDF pages** need `PyMuPDF` to rasterize (also not installed by default:
`uv add pymupdf`); without it, a `.pdf` input fails with a clear
`OcrError(code="pdf_render_unavailable")` rather than a crash, and
`--text`/`--text-file`/text-typed `--file` inputs are entirely unaffected.

### VRAM unload order (8GB GPU, one heavy model at a time)

For `--file` with an image/PDF, three model loads can potentially compete
for VRAM in sequence; the pipeline enforces this order, never two at once:

1. **OCR/VL model** (PaddleOCR process, or `qwen3-vl:2b` via Ollama) extracts text from the page.
2. **Unload it**; `qwen3-vl:2b` is unloaded via Ollama (`keep_alive=0`) immediately after extraction, whether it succeeded or raised (best-effort, in a `finally`); PaddleOCR's process-local objects go out of scope and are garbage-collected once `load_text_from_file` returns from that branch, since nothing holds a reference to the pipeline afterward.
3. **Only then** does `Pipeline.run()` load the `--provider`/`--model` generate model against the now-freed VRAM budget.
4. If repair kicks in and switches provider (default: local Ollama
   `qwen3.5:0.8b`, unless `--pin-provider`), `Pipeline.run()` unloads the
   outgoing provider's model first (`old_provider.unload(old_model)`,
   best-effort; skipped if the provider has no `unload` or
   `pin_provider=True` keeps the same one; added Phase 8). Nothing unloads
   the model a run ultimately ends on, though, so a long CLI/UI session
   still leaves the last-used model resident.

## Ollama

- Install from https://ollama.com and make sure the server is running
  (`ollama serve`, or the tray app on Windows).
- Pull the models this phase uses:
  ```
  ollama pull granite4.1:3b
  ollama pull qwen3.5:0.8b
  ```
- Check what's loaded/running: `GET http://127.0.0.1:11434/api/ps` (or
  `curl http://127.0.0.1:11434/api/tags` for what's installed).
- **8GB VRAM budget:** only one heavy model should be resident at a time.
  `OllamaProvider.unload(model)` posts `keep_alive=0` to `/api/generate` to
  free it immediately; call it before switching to a different model.
  Never load a 3B-class chat model and a VL model together (see "VRAM
  unload order" under Extract from file for the full OCR → generate
  sequence).
- **Structured output support:** `OllamaProvider.supports_json_schema()`
  checks `/api/version` once (cached on the instance) and compares against
  `0.5.0`, the version structured `format` support was added. Below that,
  the schema is embedded in a system-prompt instruction instead; this
  repo's installed Ollama (`0.34.0` as of Phase 3) is well above the
  threshold, so that fallback path is untested against a real old server.

## Common failures

| Symptom | Cause | Current handling |
|---|---|---|
| No JSON object found at all | Model refused, or replied in plain prose | `errors=[type="parse_error"]`; still goes through the retry/repair ladder like any other failure. |
| Invalid JSON / missing required field / enum mismatch | Model's JSON doesn't parse or doesn't match the schema | `ValidationError` → `errors=[ValidationIssue(loc, msg, type), ...]`; attempt 2 retries the same provider (lower temperature, errors fed back), attempt 3 switches to the repair model (see CLI's `--repair-model`/`--pin-provider`). |
| All attempts exhausted (default `max_attempts=3`) | Model consistently can't produce valid output for this schema/text | Depends on `--fallback`: `partial` (default) keeps whatever validated and fills only non-required defaults; `empty` gives `data=None`; `raise` (`--strict`) raises `PipelineFailure`, caught by the CLI. Never an uncaught exception. |
| `provider_error` in `result.errors[i].type` | Ollama unreachable, model not pulled, timeout, wrong API key/URL, etc. | Consumes an attempt like a validation failure (not a short-circuit); a repair-stage switch to a different provider can still recover from a primary-provider outage. |
| Result comes back `ok=False` but `errors` is empty | Shouldn't happen; every `ok=False` result carries at least one `ValidationIssue`, *except* a fully-reconstructable `fallback="partial"` result (see `docs/ARCHITECTURE.md`) which is `ok=False` with empty `errors` by design. If you see raw text at the app layer instead of a `StructuredResult`, that's a bug: file it. |
| `ProviderError(code="unauthorized")` from a hosted provider | Wrong/expired API key, or key set for the wrong provider | Check the env var (or explicit `api_key=`) matches the provider you constructed. |
| `ProviderError(code="not_found")` | Wrong base URL, or a model name the endpoint doesn't recognize | Check `OPENAI_BASE_URL` / the model string passed to the provider. |
| `ProviderError(code="missing_api_key"\|"missing_base_url")` | Env var unset and no explicit argument passed | Set the env var or pass the value directly when constructing the provider. |
| `OcrError(code="ocr_unavailable")` then falls through silently | PaddleOCR not installed | Expected; `qwen3-vl:2b` via Ollama runs instead. Not a failure unless that also fails. |
| `OcrError(code="ocr_failed")` from `--file` | Both PaddleOCR (if installed) and the Ollama fallback failed; check `ollama pull qwen3-vl:2b` and that Ollama is running | CLI prints the code + message and exits 1; no traceback. |
| `OcrError(code="pdf_render_unavailable")` | PyMuPDF not installed | `uv add pymupdf`, or convert the PDF page to an image yourself and pass that to `--file` instead. |
