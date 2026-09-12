# LLM Evaluation Harness

Golden-dataset evaluation harness for LLMs: run candidate models against a fixed set of
cases, score each answer with deterministic metrics and an LLM-as-judge, and fail the gate
when quality regresses against a stored baseline.

## What is measured

- **Deterministic metrics** — exact match, contains-any/all, forbidden-any, regex match,
  JSON validity, latency, response length. See [docs/METRICS.md](docs/METRICS.md).
- **Judge rubric scores** — an LLM judge scores each answer against a rubric, returned as a
  validated Pydantic schema (never trusted as raw text).
- **Regression gate** — the current run's scores are compared against a stored baseline; the
  gate exits non-zero if quality drops beyond a threshold. See [docs/GATES.md](docs/GATES.md).

## Running locally

```
run.cmd
```

Sets up a venv, installs `requirements.txt`, and launches the Streamlit UI (pick a
dataset and provider/model, run, see per-case scores and a baseline comparison).

The same pipeline runs stage by stage from the CLI:

```
python -m src.runners.candidate --dataset datasets/golden/smoke.jsonl --provider ollama --model granite4.1:3b --out reports/
python -m src.metrics --candidates reports/<run>/candidates.jsonl --dataset datasets/golden/smoke.jsonl --out reports/<run>/rule_scores.jsonl
python -m src.judge --candidates reports/<run>/candidates.jsonl --dataset datasets/golden/smoke.jsonl --provider ollama --model qwen3.5:2b --rubric answer_quality
python -m src.eval --run reports/<run> --dataset datasets/golden/smoke.jsonl
python -m src.gate --run reports/<run> --baseline baselines/current.json --config config/gate.yaml
```

See [docs/RUNBOOK.md](docs/RUNBOOK.md) for environment setup (Ollama, API keys) and the
full stage list including `src.dataset validate` and `src.gate --accept`.

## CI and hardware

CI (`../.github/workflows/llm-eval.yml`) runs on `ubuntu-latest` and does **not** require an
RTX 4060 or any GPU: it uses a cloud provider when secrets are configured, and otherwise
scores a committed, frozen candidate fixture with rule-based metrics only. A local GPU
is an optional path for running Ollama models on your own machine -- it is never a CI
requirement.

## Providers

Candidate and judge models are both selectable, independently, from:

1. **Ollama** (local) — auto-detected installed models; `granite4.1:3b` is the
   recommended candidate and the Streamlit UI's default dropdown pick, but every CLI
   requires `--model` explicitly.
2. **Agnes AI** — `agnes-2.5-flash` via an OpenAI-compatible endpoint (`AGNES_API_KEY`).
3. **OpenAI-compatible** — `gpt-5.6-luna` / `gpt-5.6-terra` (`OPENAI_API_KEY`, `OPENAI_BASE_URL`).
4. **Gemini** — `gemini-3.5-flash-lite` / `gemini-3.7-flash` (`GOOGLE_API_KEY`).

The judge is never silently the same model+prompt as the candidate when avoidable — see
[docs/RUNBOOK.md](docs/RUNBOOK.md).

## How the gate fails

`python -m src.gate --run reports/<run> --baseline baselines/current.json --config
config/gate.yaml` exits `0` (pass), `2` (a quality threshold or regression check failed),
or `3` (harness/infra error -- missing/malformed files, never a quality signal). CI
(`../.github/workflows/llm-eval.yml`) fails the job on either `2` or `3`. See
[docs/GATES.md](docs/GATES.md) for every threshold `config/gate.yaml` supports and how
`baselines/current.json` is structured.

## Non-goals

Training, a RAG index, a production chat UI, Docker. Native Windows 11, no WSL2.

## Status

All phases implemented: dataset validation, the 4 providers, the candidate runner, rule
metrics, the LLM-as-judge pipeline, run summarization, the regression gate, CI, and the
Streamlit UI.

<p align="center">Made with ❤️ by Ahmad Mujtaba</p>
