# Runbook

## Start

```
run.cmd
```

Runs `uv sync` then `uv run streamlit run src\memory\ui.py` in the
foreground of the current terminal. Serves at http://localhost:7013 (set
in `.streamlit/config.toml`).

Prerequisite: `ollama serve` running locally with at least
`qwen3-embedding:0.6b` and `qwen3.5:0.8b` pulled (`config.py`'s
`ALLOWED_OLLAMA_MODELS` lists all models the code is written to expect;
only these two are actually called by any code path -- see README
"Configuration").

## Stop

`run.cmd` runs Streamlit in the foreground; stop it with Ctrl+C in that
terminal, or close the terminal window. Nothing in this repo installs a
service, daemon, or scheduled task.

## Logs

This repo does not write its own log files. Streamlit's own output and any
Python traceback go to the terminal running the process (or, in the UI,
into the page itself as a Streamlit error box). Ollama's logs are managed
by the Ollama service outside this repo.

## Failures with a known cause

These are quoted or closely paraphrased from error text actually produced
by this code:

- **`sqlite3.ProgrammingError: SQLite objects created in a thread can
  only be used in that same thread ...`** -- would indicate
  `EpisodicMemory`'s connection is being used from a different thread
  than the one that created it. The current code opens it with
  `check_same_thread=False` specifically to prevent this
  (`episodic.py`); seeing this error again means something is
  constructing a `sqlite3.Connection` a different way.
- **`sqlite3.OperationalError: fts5: syntax error near "..."`** -- FTS5's
  query syntax treats punctuation as operators. `EpisodicMemory.search_keyword`
  sanitizes its input to bare word tokens before calling FTS5
  (`_to_fts_query`, `episodic.py`); this error recurring means something
  is querying the `episodes_fts` table directly instead of going through
  `search_keyword`.
- **`RebuildRequiredError: index_meta.json has embed_model=... , config
  expects ...`** (`semantic.py`) -- `config.EMBED_MODEL` was changed
  without rebuilding the semantic index. There is no automatic fix: delete
  `data/memory/qdrant/` and `data/memory/index_meta.json`, then re-run
  whatever code calls `SemanticMemory.upsert_fact()` for every fact that
  needs to exist again.
- **A connection error from `ollama.embed()` or `ollama.chat()`** --
  raised when Ollama is not reachable. `semantic.py` does not catch this
  (an embedding call failing there will raise). `compress.py` does catch
  it: `Compressor.compress()` falls back to an extractive summary, and
  `Distiller.distill()` returns zero facts, rather than raising further
  (see docs/TECHNICAL.md "Error handling").
- **Embedded Qdrant opened twice against the same path.** `semantic.py`'s
  docstring states the store runs embedded, in-process, with no server;
  the design implies one process can hold `data/memory/qdrant/` open at
  a time. This project was not observed to produce a specific error
  string for this case during this documentation pass -- treat it as
  unverified, and avoid running the Streamlit app and a second script
  (e.g. `scripts/seed_demo.py`) against the same `data/memory/` at once.

## Data location

All persisted memory is under `data/memory/` (gitignored except
`.gitkeep`). Deleting that directory resets working, episodic, and
semantic memory to empty; the next run recreates the SQLite schema and
Qdrant collection automatically (`EpisodicMemory.__init__`,
`SemanticMemory.__init__`).
