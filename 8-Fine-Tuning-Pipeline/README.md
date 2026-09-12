# Fine-tuning pipeline

## What this is

A pipeline that fine-tunes `Qwen/Qwen3.5-0.8B` with LoRA/QLoRA on synthetic support-ticket data
(a fixed JSON label schema — see `docs/TASK.md`), and compares it against a frozen prompt-only
baseline run through Ollama. The comparison ("bake-off") and its verdict are written to
`reports/bakeoff.md`.

## Platform

This repo is **Windows-only as written**. `train.cmd` and `run.cmd` are Windows batch files that
call `.venv\Scripts\activate.bat`, and `train.cmd` pipes through `powershell -Command`. The CUDA
wheel index in `pyproject.toml` (`https://download.pytorch.org/whl/cu130`) is gated on
`sys_platform == 'win32'`. Nothing in the repo targets Linux/macOS or WSL2/Docker (there is no
Dockerfile or compose file here).

## Requirements

Taken directly from `pyproject.toml` / `.python-version` / `uv.lock`:

- Python `>=3.13` (`.python-version` pins `3.13.15`)
- [`uv`](https://docs.astral.sh/uv/) for dependency management (`pyproject.toml` + `uv.lock` are
  the source of truth; `requirements.txt` is a pinned pip fallback, see below)
- An NVIDIA GPU with CUDA — the repo was built and tested against an 8GB card (see
  `docs/VRAM.md`); `src/train/run.py` will fall back to 8-bit or CPU/fp16 LoRA if `bitsandbytes`
  4-bit isn't usable, but this fallback path itself is unverified (see "Known limitations")
- Ollama running locally, reachable at `http://localhost:11434` (the default in
  `src/providers/ollama.py`), with the model tags used by this repo pulled: `qwen3.5:0.8b`,
  `qwen3.5:2b`, `granite4.1:3b` (see "Configuration")
- Direct dependency versions installed in this repo's `.venv` (from `pyproject.toml`): torch
  `2.14.0+cu130`, torchvision `0.29.0+cu130`, transformers `5.17.0`, peft `0.20.0`, trl `1.13.0`,
  accelerate `1.15.0`, bitsandbytes `0.50.2`, datasets `5.0.1`, huggingface-hub `1.31.0`, pydantic
  `2.13.5`, requests `2.34.2`, pyyaml `6.0.3`, streamlit `1.63.0`, pandas `3.0.5`, and pytest
  `9.1.1` (dev group) — see `docs/STACK.md` for how these were chosen and verified.

## Setup and run

Every command below is one that exists in this repo (a `.cmd` script or a `python -m` module with
a `main()`/argparse entry point) — none are illustrative.

```
uv sync
```

| Command | Does |
|---|---|
| `run.cmd` | Starts the Streamlit UI (`src/ui/app.py`) on the port/theme in `.streamlit/config.toml`. Never trains. |
| `train.cmd` | Runs `python -m src.train.run --config configs\train.yaml`, tees output to `outputs\train.log`. Never starts the UI. |
| `train.cmd --config configs\train_smoke.yaml` | Same, but the config caps training at `max_steps: 2` (a smoke test, not a real training run). |
| `uv run python -m src.data.generate --n-train 200` | Generates synthetic data via a teacher model into `data/processed/{train,val,test}.jsonl`. Flags: `--n-train`, `--n-val`, `--n-test`, `--teacher`, `--repair-model`, `--max-dup-ratio`, `--out-dir` (see `src/data/generate.py`). |
| `uv run python -m src.eval.baseline --model qwen3.5:0.8b` | Scores a prompt-only Ollama model against `data/processed/test.jsonl`, writes `reports/baseline_<model>.json` + `_errors.csv`. Flags: `--model`, `--test-file`, `--prompt-file`, `--out-dir` (see `src/eval/baseline.py`). |
| `uv run python -m src.eval.bakeoff --adapter outputs/adapters/<run_id> --baseline reports/baseline_qwen3.5_0.8b.json` | Scores the LoRA adapter the same way, writes `reports/lora_<run_id>.json` and `reports/bakeoff.md`. Flags: `--adapter`, `--baseline` (both required), `--baseline-2b`, `--test-file`, `--prompt-file`, `--out-dir`, `--judge`, `--judge-model` (see `src/eval/bakeoff.py`). |

## Configuration

**Environment variables** (the only ones read directly in `src/`, both in
`src/providers/cloud.py`): `AGNESAI_API_KEY`, `OPENAI_API_KEY` — required only if you select the
cloud teacher/judge options (`agnes-2.5-flash` / `gpt-5.6-luna`); the local Ollama path needs
neither. There is no `.env` file or `.env.example` in this repo — these are read from the process
environment directly (`os.environ.get`).

**Config files:**

- `configs/train.yaml` — training config (`base_model_id`, dataset paths, quantization, LoRA
  params, learning rate/epochs/seq_len, `output_dir`). Loaded by `src/train/run.py`.
- `configs/train_smoke.yaml` — same shape, plus `max_steps: 2`.
- `configs/baseline_prompt.txt` — the system prompt used by both the baseline and the LoRA eval.
  Per its own module docstring in `src/eval/baseline.py`, this is meant to be frozen after the
  baseline is first run (typo fixes only) so later results are comparable.
- `.streamlit/config.toml` — `[server] port = 7012`, `[theme] base = "dark"`.

## Repo map

```
src/
  data/       schema.py (Pydantic models: TicketTarget, GeneratedRow, TicketExample; parsers;
              load_examples), generate.py (synthetic data generator + CLI)
  providers/  base.py (TeacherClient/ChatClient protocols), ollama.py (HTTP client for local
              Ollama), cloud.py (OpenAI-compatible HTTP client for Agnes AI / OpenAI)
  train/      run.py (LoRA/QLoRA training via transformers + peft + trl)
  eval/       baseline.py (prompt-only scoring + reports), bakeoff.py (LoRA scoring + bakeoff.md)
  ui/         app.py (Streamlit control panel)
configs/      train.yaml, train_smoke.yaml, baseline_prompt.txt
docs/         STACK.md, TASK.md, VRAM.md, EVAL.md, ARCHITECTURE.md, TECHNICAL.md, RUNBOOK.md
data/processed/   generated datasets (jsonl) — currently only train.jsonl (3 rows) exists
reports/      baseline_*.json/csv, lora_*.json/csv, bakeoff.md
outputs/adapters/<run_id>/  trained LoRA adapters (HF PEFT format) + train_meta.json
tests/        pytest suite
```

## Tests

```
uv run pytest
```

`pyproject.toml` sets `[tool.pytest.ini_options] pythonpath = ["."]`. Test files:
`tests/test_schema.py`, `tests/test_generate.py`, `tests/test_baseline.py`,
`tests/test_bakeoff.py`. All tests use canned/fake model clients — none call Ollama, a cloud API,
or load a real Hugging Face model.

## Known limitations (observed in this repo's current state)

- **`data/processed/` has only `train.jsonl`** (3 rows). There is no `val.jsonl` or `test.jsonl` in
  this repo, so `src/eval/baseline.py`'s and `src/eval/bakeoff.py`'s default `test.jsonl` path
  will not resolve until `src/data/generate.py` is run for real.
- **Exactly one adapter exists**, `outputs/adapters/20260912-193951/`. Its `train_meta.json` shows
  `"dry_run": true, "max_steps_arg": 2, "num_train_examples": 3` — it was trained (and, per
  `reports/lora_20260912-193951.json`, evaluated) on the same 3 rows. The improvement recorded in
  `reports/bakeoff.md` is not evidence of generalization.
- **No `reports/baseline_qwen3.5_2b.json` exists**, so the "baseline (2b)" column described in
  `docs/EVAL.md` has never appeared in an actual `bakeoff.md`.
- **The `--judge` flag in `src/eval/bakeoff.py` has no corresponding call to it anywhere in this
  repo** (no script, no test invokes it with real models) — its logic is covered only by
  `tests/test_bakeoff.py`'s canned-reply tests.
- **`src/train/run.py`'s 8-bit/fp16 fallback branches** (`resolve_quantization`) have no
  corresponding test or recorded run — only the 4-bit path has a verified `train_meta.json`.
- Per `docs/STACK.md`, Unsloth was evaluated and deliberately not used (pinned `torch<2.13.0`
  conflicts with the `torch==2.14.0+cu130` this repo installs).
- There is no code path in this repo that merges a LoRA adapter into a full model or converts one
  to GGUF for Ollama serving; `outputs/adapters/<run_id>/` is HF PEFT format only.

`docs/CONTRIBUTING.md` is omitted: there is no CI configuration, no `.git` history in this
checkout, no LICENSE, and no branching/PR convention anywhere in the tree to document. The only
verifiable contribution expectation is that `uv run pytest` passes, which is covered above.

<p align="center">Made with ❤️ by Ahmad Mujtaba</p>
