# Runbook

A `RUNBOOK.md` already exists at the repo root (written in an earlier documentation pass, covering
the same one-time-setup/command list as `README.md` above). This file is the version requested at
`docs/RUNBOOK.md`; the two currently overlap — see the note at the end of this session's summary.

## Start

- UI: `run.cmd` (from the repo root, in `cmd.exe` or PowerShell). Starts Streamlit on the port set
  in `.streamlit/config.toml` (`7012`).
- Training: `train.cmd` (default `configs/train.yaml`) or `train.cmd --config
  configs\train_smoke.yaml` (2-step smoke test). Requires `.venv` to already exist
  (`call .venv\Scripts\activate.bat` — `train.cmd`/`run.cmd` do not create the venv themselves; run
  `uv sync` first).
- Everything else (`src.data.generate`, `src.eval.baseline`, `src.eval.bakeoff`) is invoked with
  `uv run python -m <module> [flags]` — see `README.md` "Setup and run" for the exact commands and
  flags, taken from each module's `argparse` definition.

## Stop

- UI / training: close the terminal window, or `Ctrl+C` in the window running `run.cmd`/
  `train.cmd`. Neither script installs a signal handler or writes a PID file, so there is no other
  documented stop mechanism in this repo.
- `train.cmd` runs `python -m src.train.run` through `powershell -Command "... | Tee-Object
  -FilePath outputs\train.log"`; killing the terminal kills the whole pipeline (PowerShell,
  python, and the Tee-Object stream).

## Logs

- `outputs/train.log` — written only by `train.cmd`'s `Tee-Object` redirection, not by any Python
  code directly. If you run `python -m src.train.run` directly (bypassing `train.cmd`), this file
  is not created. The Streamlit UI (`src/ui/app.py`) tails the last 200 lines of this file every 3
  seconds if it exists, and says "No log at ... — nothing running" if it doesn't.
- All other modules log to stdout/stderr only (Python `logging`, `level=logging.INFO`) — there is
  no other log file in this repo.

## Failures you can infer from the code's own error strings

| Where | Message (from source) | Likely cause / what to check |
|---|---|---|
| `src/data/generate.py`, `generate_rows` | `"diversity check failed: N% duplicate first-20-chars ticket prefixes (max allowed 40%); teacher is producing repetitive templates"` | The teacher model (`--teacher`, default `granite4.1:3b`) is returning near-identical ticket text across calls. Uncaught — the process exits with a traceback. |
| `src/providers/cloud.py`, `OpenAICompatTeacher.complete` | `"required environment variable {NAME} is unavailable; relaunch the host if it was recently configured."` | `AGNESAI_API_KEY` or `OPENAI_API_KEY` isn't set in the process environment. Uncaught by the caller. |
| `src/providers/__init__.py`, `get_teacher` | `"unknown teacher {name!r}; choices: [...]"` | A `--teacher`/`--judge-model` value isn't one of the five hardcoded keys (`granite4.1:3b`, `qwen3.5:0.8b`, `qwen3.5:2b`, `agnes-2.5-flash`, `gpt-5.6-luna`). |
| `src/train/run.py`, around `trainer.train()` | logged: `"CUDA OOM during training. Cut, in this order: ..."` | Caught: `torch.OutOfMemoryError` → the log line names which config value to reduce first, then `sys.exit(1)`. |
| `src/eval/bakeoff.py`, `main()` | logged: `"adapter missing: no train_meta.json under {path}"` | The `--adapter` directory doesn't contain a `train_meta.json` (training hasn't produced an adapter there). `bakeoff.md` is written saying "adapter missing," then `sys.exit(1)`. |
| Any HTTP call in `src/providers/ollama.py` | `requests` raises on connection refused / non-2xx (`resp.raise_for_status()`) | Ollama isn't running, isn't on `localhost:11434`, or the requested model tag isn't pulled. Uncaught here. |

## Unknown / not documented anywhere in this repo

- No documented recovery procedure for a corrupted or partial `outputs/adapters/<run_id>/`
  directory.
- No documented disk-space or Hugging Face cache-eviction policy.
- No documented behavior for running two instances of `run.cmd`/`train.cmd` at once (e.g. two
  processes writing to `outputs\train.log` simultaneously) — not tested, not addressed in code.
