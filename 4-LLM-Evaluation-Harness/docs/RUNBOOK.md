# Runbook

## Environment

Copy `.env.example` to `.env` and fill in the keys for whichever providers you use:

| Var | Provider |
|---|---|
| `AGNES_API_KEY` | Agnes AI |
| `OPENAI_API_KEY`, `OPENAI_BASE_URL` | OpenAI-compatible |
| `GOOGLE_API_KEY` | Gemini |

Ollama needs no key — it's detected locally.

## Ollama (local models)

Requires Ollama installed and running natively on Windows (no WSL2, no Docker). Only
these models are used by this repo's jobs:

- `granite4.1:3b` — recommended candidate, and recommended local judge when the
  candidate used a different model. It's the Streamlit UI's default dropdown selection
  for Ollama, but every CLI (`src.runners.candidate`, `src.judge`) requires `--model`
  explicitly every time -- nothing auto-selects it.
- `qwen3.5:2b` — cheap candidate alternative.
- `qwen3.5:0.8b` — tiny parse/repair of judge JSON output (see docs/METRICS.md).

After all cases in a run finish, `src.runners.candidate` and `src.judge` each explicitly
unload their Ollama model (`keep_alive=0`) rather than waiting on Ollama's own idle
timeout -- so the candidate and judge stages don't contend for VRAM on an 8 GB card. The
JSON-repair pass does the same for `qwen3.5:0.8b` after each repair call. This is
best-effort (a failed unload call is logged, never raised) and only fires when the
provider in question is `ollama`.

**Thinking models and JSON output:** `qwen3.5:2b` and `qwen3.5:0.8b` are "thinking"
models -- left to their defaults, they can spend their entire output budget on
chain-of-thought and never emit the JSON verdict the judge/repair prompts demand
(observed live as `done_reason: "length"` with an empty `message.content`). Both the
judge call and the repair call pass `think=False` to `OllamaProvider.complete()`
specifically to prevent this; candidate calls are unaffected (thinking is left to the
model's default there, since a candidate answer doesn't need to fit a strict schema).

## Running without a GPU

If no local GPU/Ollama is available (e.g. a CI runner):

- Skip the local judge entirely, or
- Use a cloud judge (Agnes AI / OpenAI-compatible / Gemini) instead.

The candidate model must also come from a cloud provider in this case — Ollama requires
a local GPU-capable machine.

## Judge model selection

There is no automatic judge-model selection: `python -m src.judge` requires an explicit
`--provider`/`--model` every run, same as the candidate runner. The harness's actual
safeguard against self-judging is passive, not a picker: if the judge's provider+model
matches the candidate's, each `JudgeRecord` is flagged `same_model_warning: true` and the
CLI prints a warning to stderr (scores are still produced -- nothing is blocked).

Recommended pairing to avoid self-judging (not enforced by the code, just a convention
to follow when choosing `--model`):

- Candidate `qwen3.5:*` -> judge `granite4.1:3b`.
- Candidate `granite4.1:3b` -> prefer a cloud judge if any cloud API key is set;
  otherwise you'll get the `same_model_warning` if you pass the same model as judge.

## Running the pipeline stage by stage

```
python -m src.dataset validate datasets/golden
python -m src.runners.candidate --dataset datasets/golden/smoke.jsonl --provider ollama --model granite4.1:3b --out reports/
python -m src.metrics --candidates reports/<run>/candidates.jsonl --dataset datasets/golden/smoke.jsonl --out reports/<run>/rule_scores.jsonl
python -m src.judge --candidates reports/<run>/candidates.jsonl --dataset datasets/golden/smoke.jsonl --provider ollama --model qwen3.5:2b --rubric answer_quality
python -m src.eval --run reports/<run> --dataset datasets/golden/smoke.jsonl
python -m src.gate --run reports/<run> --baseline baselines/current.json --config config/gate.yaml
python -m src.gate --accept reports/<run>   # local only -- refuses to run when CI is set
```

`src.runners.candidate` also takes `--run-id <id>` (reuse a specific run directory
instead of generating a fresh one) and `--resume` (skip case ids already present in that
run's `candidates.jsonl`). **`--resume` alone does nothing useful** -- each invocation
generates a new `run_id` unless you also pass back the same `--run-id` from the run
you're resuming; without it, `--resume` just finds nothing to skip in a brand-new,
empty directory.

`run.cmd` instead launches the Streamlit UI (`src/ui/app.py`), which runs the same
functions in-process from a browser: pick a dataset, candidate/judge provider and model,
click "Run evaluation", see the per-case table and a baseline comparison. Its "write
local baseline" button is disabled until you either check the sidebar confirmation or
open the page with `?confirm=1`.

## CI (`../../.github/workflows/llm-eval.yml`)

Runs on `ubuntu-latest`, no Docker, no GPU -- **CI does not require an RTX 4060 or any
GPU.** The local-GPU/Ollama path above is optional, for your own machine only; CI never
depends on it. If any cloud provider secret
(`GOOGLE_API_KEY`, `AGNES_API_KEY`, or `OPENAI_API_KEY`+`OPENAI_BASE_URL`) is set on the
repo, it runs the real candidate + judge pipeline against that provider. Otherwise it
scores `tests/fixtures/frozen_candidates.jsonl` (a committed, fixed set of answers) with
`src.metrics` only, so the gate still checks regex/contains/json-validity even with zero
secrets configured -- `config/gate.yaml`'s `allow_missing_judge: true` is what keeps a
missing judge from failing that path. The job fails whenever `src.gate` exits `2` or `3`
(GitHub Actions fails a job on any non-zero step exit code, so no extra handling is
needed for that).
