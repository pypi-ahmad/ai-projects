# Technical notes

Covers only rationale that the code (comments/docstrings) or existing `docs/` files actually
state. See `docs/STACK.md` for the full model/version verification record and `docs/VRAM.md` for
measured memory numbers.

## Why these libraries (per code/comments/docs/STACK.md)

- **torch CUDA wheel via a custom index**; `pyproject.toml`'s `[tool.uv.sources]` points
  `torch`/`torchvision` at `https://download.pytorch.org/whl/cu130`, gated on
  `sys_platform == 'win32'`. Per `docs/STACK.md`, this is because PyPI's default `win_amd64` torch
  wheel is CPU-only; `uv add torch` alone resolves to that CPU wheel, and `--torch-backend` (uv's
  auto-CUDA-selection flag) only affects `uv pip install`, not project `uv add`/`uv sync`.
- **bitsandbytes 4-bit (QLoRA)**; `src/train/run.py`'s `probe_bnb_4bit`/`resolve_quantization`
  try 4-bit first and fall back to 8-bit, then plain fp16 LoRA (forcing `seq_len=256`,
  `batch_size=1` in that last case). Per `docs/STACK.md`, 4-bit was chosen because it was verified
  working on this repo's GPU; the fallback branches exist in code but have no recorded successful
  run (see `README.md` "Known limitations").
- **`attn_implementation="sdpa"`** (`src/train/run.py`); no flash-attention is used or installed;
  `sdpa` is torch's built-in attention kernel.
- **TRL's prompt/completion dataset format + `completion_only_loss`, not `messages` +
  `assistant_only_loss`**; `build_dataset`'s docstring in `src/train/run.py` states this directly:
  the base model's chat template has no `{% generation %}` marker, so `assistant_only_loss` (which
  needs that marker) would silently mask the entire sequence to zero loss. The prompt/completion
  split doesn't depend on that marker, since TRL derives the mask by diffing tokenized prompt vs.
  prompt+completion.
- **Un-tuned LoRA `target_modules` list includes `in_proj_qkv`/`out_proj`, not just
  `q_proj/k_proj/v_proj/o_proj`**; the comment in `configs/train.yaml` states the base model is a
  hybrid-attention architecture where most decoder layers use a different attention block whose
  projections are named `in_proj_qkv`/`out_proj` rather than the standard four; targeting only the
  standard names would leave most layers untouched.
- **`OllamaTeacher.chat(..., think=False)` by default**; the comment in
  `src/providers/ollama.py` states that thinking-capable models can put their answer in a separate
  `message.thinking` field and leave `message.content` empty if generation is cut off mid-thought;
  since only `content` is scored, thinking is left off.
- **`MAX_NEW_TOKENS = 200`** in `src/eval/bakeoff.py`; the comment there states this is because
  the Ollama-based baseline left `num_predict` unbounded (no explicit cap was set in
  `src/providers/ollama.py`'s request body), while `model.generate()` requires an explicit
  `max_new_tokens`; 200 is called "generous headroom," not a measured-equivalent value.
- **`dataloader_num_workers=0`** in `src/train/run.py`'s `SFTConfig`; inline comment: "Windows:
  worker subprocesses are unreliable/slow here."
- **Pydantic** (`src/data/schema.py`) for `TicketTarget`/`GeneratedRow`/`TicketExample`, and the
  `--judge` verdict in `src/eval/bakeoff.py` (`JudgeVerdict`); used to validate/reject model and
  teacher output, not just as a data container: `parse_generated_row`/`parse_ticket_target`
  deliberately raise `ValueError` on schema mismatch rather than accepting partial data.

## Invariants

- `TicketTarget`'s four fields (`priority`, `product`, `sentiment`, `next_action`) are closed
  `Literal` enums (`src/data/schema.py`); there is no free-text label path.
- `configs/baseline_prompt.txt` is meant to stay fixed once the baseline has been run once; the
  module docstring of `src/eval/baseline.py` states it is "frozen ... so later phases can't
  retroactively flatter the baseline by tuning its prompt."
- Training only ever produces an adapter, never a merged full model; `src/train/run.py` calls
  `trainer.model.save_pretrained(adapter_dir)` on the `PeftModel`, which saves adapter weights
  only; there is no merge step anywhere in `src/`.
- `src/eval/bakeoff.py` scores the LoRA adapter through the exact same `run_baseline`/`score_one`
  function used for the Ollama baseline (`LocalAdapterModel` implements the same `ChatClient`
  shape); the two are not scored by separate/divergent code paths.

## Error handling

- **Bad teacher/model JSON**; `src/data/schema.py`'s `parse_generated_row`/`parse_ticket_target`
  strip a leading/trailing markdown code fence, then raise `ValueError` on invalid JSON or schema
  mismatch. Callers (`src/data/generate.py`'s `generate_rows`, `src/eval/baseline.py`'s
  `score_one`) catch `ValueError` and record the row as invalid/dropped rather than crashing.
- **Data-generation diversity check**; `src/data/generate.py`'s `generate_rows` raises a plain
  `RuntimeError` ("diversity check failed: ...% duplicate first-20-chars ticket prefixes...") if
  more than `--max-dup-ratio` (default 0.4) of generated tickets share a first-20-character prefix.
  This is uncaught in `main()`; it will end the process with a traceback.
- **Missing cloud API key**; `src/providers/cloud.py`'s `OpenAICompatTeacher.complete` raises
  `RuntimeError(f"required environment variable {self.api_key_env} is unavailable; relaunch the
  host if it was recently configured.")` if the configured env var isn't set. Uncaught in callers.
- **Unknown teacher/judge model name**; `src/providers/__init__.py`'s `get_teacher` raises
  `ValueError` listing the valid choices.
- **CUDA out-of-memory during training**; `src/train/run.py` catches
  `torch.OutOfMemoryError` around `trainer.train()`, logs an ordered list of which config value to
  reduce first (batch/grad-accum, then seq_len, then confirm 4-bit is active, then LoRA rank), and
  calls `sys.exit(1)`.
- **Missing adapter at bake-off time**; `src/eval/bakeoff.py`'s `main()` checks for
  `train_meta.json` under `--adapter` before loading anything; if absent, it writes
  `reports/bakeoff.md` with an "adapter missing" message (`write_adapter_missing_md`) and calls
  `sys.exit(1)`, instead of producing a table of fabricated/degenerate scores.
- **Unparseable judge reply** (`src/eval/bakeoff.py`'s `judge_one`); caught broadly
  (`except Exception`) and counted as a `"tie"` verdict rather than crashing the bake-off run.

## Persistence paths

See "On-disk state" in `docs/ARCHITECTURE.md` for the full list
(`data/processed/`, `outputs/adapters/<run_id>/`, `outputs/train.log`, `reports/`).
