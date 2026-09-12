# Runbook

This is a single-user desktop tool, not a hosted service: there is no
process supervisor, no restart policy, and no centralized log file. Start
and stop it by hand.

## Start

```
run.cmd
```

(double-click it, or run it from a shell in the repo root). It creates
`.venv` and installs `requirements.txt` on first run, then starts Streamlit
on **http://localhost:5805**. It requires `uv` on `PATH` and an `.env` file
with `OPENAI_API_KEY` already in place (see [README.md](../README.md)) — it
does not create `.env` for you.

Equivalent manual command (what `run.cmd` itself runs):

```
uv run --no-project --python .venv\Scripts\python.exe -m streamlit run src/ui/app.py --server.port=5805 --logger.level=info
```

## Stop

Close the terminal window running `run.cmd`, or `Ctrl+C` in it. There is no
background service to separately stop.

`run.cmd` itself kills anything already listening on port 5805 before it
starts (`netstat` + `taskkill /F` on the owning PID) — so restarting it is
safe even if a previous instance is still running or didn't shut down
cleanly.

## Where logs go

There is no log file. Everything goes to the console `run.cmd` is running
in:

- Streamlit's own server output (`--logger.level=info`).
- `[ADE] ...`-prefixed `print()` lines from `src/graph.py` (`node_preprocess`,
  `node_parse`) — e.g. `[ADE] preprocess: <path>`, `[ADE] parse: ok, N page(s) -> <path>`,
  `[ADE] annotate: skipped (<exception>)`.

Per-page API call detail (HTTP status, request id, classified outcome,
content-filter annotations, token counts — never response text or
credentials) is not printed to the console at all; it's returned in-band as
`ParseResult.page_diagnostics`, persisted in `data/parse/<doc_sha>.json`,
and shown in the UI's collapsed **"API diagnostics"** expander after a run.

## Failures you can infer from the source

| Symptom / exact string | Where | Meaning |
|---|---|---|
| `uv is required. Install uv, then run this launcher again.` | `run.cmd` | `uv` isn't on `PATH`. |
| `Existing .venv has no Python executable. Repair it before launching.` | `run.cmd` | `.venv` exists but `.venv\Scripts\python.exe` is missing — delete/repair `.venv` and rerun. |
| `Setup failed. Streamlit was not started.` | `run.cmd` | `uv venv` or `uv pip install` failed; the actual `uv` error printed just above this line is the real cause. |
| `OPENAI_API_KEY is not set` (`ExtractConfigError`) | `src/extract.py` `_build_llm` | No key in the environment/`.env`. |
| `Unsupported model` (`ExtractConfigError`, or plain `ValueError` in `parse_document`) | `src/extract.py`, `src/parse.py` | A model id outside `MODEL_RATES` (`src/models.py`) was requested. There is no fallback model — the call is rejected before any request is sent. |
| `file not found: <path>` / `unsupported file type: <suffix>` / `PDF has no pages: <path>` (`PreprocessError`) | `src/preprocess.py` | Bad path, or a file extension outside the accepted raster types (`.png/.jpg/.jpeg/.webp/.tif/.tiff`) plus `.pdf`, or an empty PDF. |
| UI banner **"Layout parsing incomplete"** / **"Layout parsing failed"** | `src/ui/app.py`, driven by `parse_error` in the graph result | Some or all pages didn't parse. Check the **API diagnostics** expander for the per-page `outcome` (`content_filtered`, `refused`, `incomplete`, `invalid_response`, `http_error`, `transport_error`). |
| `Pages rejected by content filter: <list>` | `src/graph.py` `node_parse` | One or more pages came back with `finish_reason == "content_filter"` or a filtered annotation; see [docs/CONTENT-FILTER-DIAGNOSTICS.md](CONTENT-FILTER-DIAGNOSTICS.md) for a worked example. |
| `'run.cmd' is not recognized as an internal or external command` | seen from `tests/test_launcher.py`'s subprocess test in this environment | Not a runtime failure of the app itself — it showed up only when pytest spawned `cmd.exe` from inside a non-native shell (Git Bash) while writing this documentation. Unconfirmed whether it reproduces from a native `cmd.exe`/Explorer double-click; see [README.md](../README.md#running-tests). |

## What this runbook doesn't cover

There's no commit/review/audit path to operate — it's dormant (see
[docs/COMPLIANCE.md](COMPLIANCE.md)) — and no deployment target beyond a
single Windows machine running `run.cmd` locally.
