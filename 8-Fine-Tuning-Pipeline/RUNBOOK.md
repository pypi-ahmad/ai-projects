# Runbook

Native Windows 11, RTX 4060 Laptop (8GB VRAM), no WSL2, no Docker. See `docs/STACK.md` for the
full stack decision and `docs/TASK.md` for the task/schema. (`docs/ARCHITECTURE.md`, `docs/VRAM.md`,
`docs/EVAL.md`, and `README.md` from the original Phase 1 scope were never written — this repo
has grown phase-by-phase and those didn't end up load-bearing for any later phase.)

## One-time setup

```
uv sync
```

Ollama must be running locally with `qwen3.5:0.8b`, `qwen3.5:2b`, and `granite4.1:3b` pulled
(baseline/teacher models — see `docs/STACK.md`; these are never the LoRA train base).

## Commands

| Command | What |
|---|---|
| `run.cmd` | Starts the Streamlit UI only. Never trains. |
| `train.cmd` | Trains, per `configs/train.yaml`. Never starts the UI. Tees output to `outputs\train.log`. |
| `train.cmd --config configs\train_smoke.yaml` | 2-step smoke test — proves the pipeline runs end-to-end in about a minute. The resulting adapter is not meant to be evaluated for real quality. |

## Full pipeline, in order

1. `uv run python -m src.data.generate --n-train 200` — writes `data/processed/{train,val,test}.jsonl` via the teacher model.
2. `uv run python -m src.eval.baseline --model qwen3.5:0.8b` (and optionally `--model qwen3.5:2b`) — writes `reports/baseline_*.json`. This is the frozen number LoRA has to beat; `configs/baseline_prompt.txt` is not edited after this except typos.
3. `train.cmd` — trains the adapter, writes `outputs/adapters/<run_id>/` (adapter-only, plus `train_meta.json`).
4. `uv run python -m src.eval.bakeoff --adapter outputs/adapters/<run_id> --baseline reports/baseline_qwen3.5_0.8b.json` — writes `reports/lora_<run_id>.json` and `reports/bakeoff.md`.
5. `run.cmd` — browse the dataset histogram and the last `bakeoff.md` from the UI.

If step 3 was skipped, step 4 (or the UI's "Last bake-off" panel) reports **adapter missing**, not
fabricated scores.

## Smoke-testing without a real run

`configs/train_smoke.yaml` caps training at 2 steps (`max_steps: 2`) so you can prove the full
stack — model download, 4-bit load, LoRA, a training step, adapter save — actually works on this
machine without committing to a real multi-epoch run. Use it the same way as `train.cmd`, just
pointed at the smoke config:

```
train.cmd --config configs\train_smoke.yaml
```

(`train.cmd` hardcodes `--config configs\train.yaml` first and forwards extra args after it;
argparse takes the last `--config` it sees, so this overrides it to the smoke config.)
