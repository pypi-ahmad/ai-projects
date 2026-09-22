# Runbook

This is a single-user desktop tool. It has no process supervisor, restart
policy, or centralized log file, so you start and stop it by hand.

## Start

```powershell
.\run.cmd
```

(Double-click it, or run it from a shell in the repo root.) It creates
`.venv` and installs `requirements.txt` on first run, then starts Streamlit
on **http://localhost:5805**. It requires `uv` on `PATH`; extraction requires
`OPENAI_API_KEY` in the inherited environment or an optional project-local
`.env` (see [README.md](../README.md)). It does not create `.env`.

Equivalent manual command (what `run.cmd` itself runs):

```
uv run --no-project --python .venv\Scripts\python.exe -m streamlit run src/ui/app.py --server.port=5805 --logger.level=info
```

## Stop

Close the terminal window running `run.cmd`, or `Ctrl+C` in it. There is no
background service to separately stop.

`run.cmd` force-terminates any process already listening on port 5805 before
starting (`netstat` + `taskkill /F` on the owning PID). Check that the port is
not being used by an unrelated application before running the launcher.

## Parse and inspect results

Upload an image or PDF, select an inclusive page range, and click **Parse**.
End page `0` in the UI means the last page. Raster images are treated as one
page. Corrupt uploads and invalid ranges are rejected before extraction.
Different bytes under the same filename reset the detected range and old result.

The model is fixed to GPT-6 Sol. Progress counts completed, successful, and
failed page calls; artifact generation follows. Only the active preview tab is
rendered, and switching tabs does not request another extraction. Successful
pages remain available when others fail. JSON/Markdown previews use the current
in-memory result; PDF/PNG previews use that run's returned artifact paths.

Graph artifacts are isolated under `data/parse/runs/<run_id>/`. Legacy files
are not automatically moved or deleted. Session usage totals live in Streamlit
session state, not a persistent billing ledger.

## Where logs go

There is no log file. `run.cmd` writes everything to its console:

- Streamlit's own server output (`--logger.level=info`).
- `[ADE] ...`-prefixed `print()` lines from `src/graph.py` (`node_preprocess`,
  `node_parse`); e.g. `[ADE] preprocess: <path>`, `[ADE] parse: ok, N page(s) -> <path>`,
  `[ADE] annotate: skipped (<exception>)`.

Per-page API call detail (HTTP status, request id, classified outcome,
content-filter annotations, token counts; never response text or
credentials) is not printed to the console at all; it's returned in-band as
`ParseResult.page_diagnostics`, persisted in `data/parse/runs/<run_id>/<doc_sha>.json`,
and shown in the UI's collapsed **"API diagnostics"** expander after a run.

## Failures you can infer from the source

| Symptom / exact string | Where | Meaning |
|---|---|---|
| `uv is required. Install uv, then run this launcher again.` | `run.cmd` | `uv` isn't on `PATH`. |
| `Existing .venv has no Python executable. Repair it before launching.` | `run.cmd` | `.venv` exists but `.venv\Scripts\python.exe` is missing; delete/repair `.venv` and rerun. |
| `Setup failed. Streamlit was not started.` | `run.cmd` | `uv venv` or `uv pip install` failed; the actual `uv` error printed just above this line is the real cause. |
| `OPENAI_API_KEY is not set` (`ExtractConfigError`) | `src/extract.py` `_build_llm` | No key in the environment/`.env`. |
| `Unsupported model` (`ExtractConfigError` or `ValueError`) | `src/extract.py`, `src/parse.py`, `src/graph.py` | A model other than `gpt-6-sol` was requested. There is no fallback; rejection precedes API calls. |
| `file not found: <path>` / `unsupported file type: <suffix>` / `PDF has no pages: <path>` (`PreprocessError`) | `src/preprocess.py` | Bad path, or a file extension outside the accepted raster types (`.png/.jpg/.jpeg/.webp/.tif/.tiff`) plus `.pdf`, or an empty PDF. |
| UI banner **"Layout parsing incomplete"** / **"Layout parsing failed"** | `src/ui/app.py`, driven by `parse_error` in the graph result | Some or all pages didn't parse. Check the **API diagnostics** expander for the per-page `outcome` (`content_filtered`, `refused`, `incomplete`, `invalid_response`, `http_error`, `transport_error`). |
| `Pages rejected by content filter: <list>` | `src/graph.py` `node_parse` | One or more pages came back with `finish_reason == "content_filter"` or a filtered annotation; see [docs/CONTENT-FILTER-DIAGNOSTICS.md](CONTENT-FILTER-DIAGNOSTICS.md) for a worked example. |
| `Cannot read this document. Upload a valid image or PDF.` | `src/ui/app.py` | Saving the upload or checking its page count failed; no extraction request was made. |
| `Page range must be within 1..<total>` / `Invalid page range` / `Raster images have only one page` | UI or `src/preprocess.py` | The requested range is invalid; it is not silently clamped. |

See [the Sol comparison](SOL-RESOLUTION-EVALUATION.md) for the separate paid
evaluation command and its limits. The normal app does not enforce that
evaluator's $2 budget, ten-request cap, or no-retry setting.

## What this runbook doesn't cover

The commit, review, and audit path is dormant (see
[docs/COMPLIANCE.md](COMPLIANCE.md)). The application has no deployment target
beyond a single Windows machine running `run.cmd` locally.
