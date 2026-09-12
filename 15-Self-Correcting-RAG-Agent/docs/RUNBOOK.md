# Runbook

## Start

```
run.cmd
```
or, with `uv` already set up:
```
uv sync --all-groups
uv run streamlit run src/self_correcting_rag/ui/app.py
```
The app serves on `http://localhost:7019` (`.streamlit/config.toml`; no `--server.port` flag
is needed). Ollama must be running and reachable at `OLLAMA_HOST` (default
`http://127.0.0.1:11434`) for the default provider -- the UI does not check this itself;
`run.cmd` does, with `ollama list`.

Without the UI:
```
uv run python -m self_correcting_rag.index --input <folder> --index data/indexes
uv run python -m self_correcting_rag.agent --q "your question" --index data/indexes
uv run python -m self_correcting_rag.eval --qa data/eval/qa.jsonl --index data/indexes
```

## Stop

Ctrl+C in the terminal running `streamlit run` (or `run.cmd`, which runs it in the
foreground). There is no background service, daemon, or process manager in this repository --
stopping the terminal's process stops the app. Ollama itself (if installed as a service) is
managed independently of this project.

## Logs

No log file is configured anywhere in this code -- `logging.basicConfig` (or any handler
setup) is never called. Three modules call `logging.getLogger(__name__)` and log at
`warning` level: `config.py`, `ingest/pipeline.py`, `web/fetch.py`. Without a configured
handler, Python sends these to stderr in whatever terminal is running the process. There is
no dedicated log file to check -- read the terminal output.

## Common failures

From error strings and log messages that actually appear in the code:

| Symptom | Source | Likely cause / action |
|---|---|---|
| `error: <message>` printed, then the process exits | `agent/__main__.py`, `eval/__main__.py` (catching `llm/base.py:ProviderConfigError`) | A non-`ollama` provider was selected (`--provider agnes\|openai_compatible\|gemini`) without its required env var(s) set. Set them in `.env` or select `--provider ollama`. |
| `WARNING: could not reach Ollama (ollama list failed)` | `run.cmd` | Ollama isn't installed or isn't running. Install/start it, then re-run `run.cmd`. |
| `SEARCH_API_KEY is not set; forcing web_enabled=False at startup` | `config.py:Settings.resolve_web_enabled()` | Web fallback was requested (`--web` flag or the UI toggle) without `SEARCH_API_KEY` configured. This is expected behavior, not a bug -- set the key in `.env` if web fallback is wanted. |
| `"internal error: <message>"` in an `AgentResult`'s `reason` field (UI shows this as an abstain) | `agent/loop.py:run_safe()` | Any unhandled exception during the loop was caught and converted to an abstain. One known cause: a small model (`qwen3.5:0.8b` by default for rewrite/critique) producing malformed JSON on both its original response and the one automatic repair attempt. Not necessarily reproducible -- retry the same question. |
| A raw Python traceback ending in `pydantic.ValidationError`, from `python -m self_correcting_rag.agent` directly | `agent/json_llm.py:call_json()` via `agent/loop.py:run()` | Same underlying cause as above, but the `agent` CLI calls `run()` directly, not `run_safe()`, so this is not caught. Re-run the command. |
| `RuntimeError("agent loop exceeded max_iters...")` | `agent/loop.py:run()` | Should not happen in normal operation -- indicates the retry-bounding invariant in `enforce_decision()` broke. Worth reporting/investigating if seen, not a transient condition to retry past. |
| Retrieval or the agent loop runs but returns nothing, with no error message | `index/vector_store.py`, `retrieve/dense.py`, `retrieve/lexical.py` | No index exists yet at the given `--index` path, or it points at the wrong directory. Dense search and BM25 search both return an empty list rather than raising when the collection/index files don't exist -- this fails quietly. Run `self_correcting_rag.index` first. |
| A web-fallback answer is missing citations you expected, with no visible error | `web/fetch.py:fetch_web_chunks()` | A per-query search failure or per-URL fetch failure is caught and logged as a `warning`, not raised. Check stderr for `"web search failed for query %r, skipping"` or `"web fetch failed for %s, skipping"`. |
| `pip install failed. See the error above.` | `run.cmd` | Installing `requirements.txt` failed -- check network access, and that a build backend (`uv_build`, needed for the editable `-e .` entry at the top of `requirements.txt`) can be fetched. |
| `unsupported extension: <ext>` (`ValueError`) | `ingest/parsers.py:parse_file()` | Should not occur via the `index` CLI, which only discovers `.txt`/`.md`/`.pdf` files (`discover_files()`); would indicate `parse_file()` was called directly with an unsupported path. |

## Rebuilding the index

`data/indexes/` is listed in `.gitignore` and safe to delete. Deleting it and re-running
`self_correcting_rag.index` rebuilds both the Qdrant collection and the `bm25s` lexical index
from the `--input` folder from scratch.
