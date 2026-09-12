# VRAM plan

GPU: RTX 4060 Laptop, 8188 MiB total (see `docs/STACK.md`). Numbers below are measured, not
estimated — from the real `--max-steps 2` dry run in Phase 4/5 (`outputs/adapters/20260912-193951/train_meta.json`).

## Planned / default config (`configs/train.yaml`)

| Setting | Value |
|---|---|
| quantization | 4bit (nf4, double quant, bf16 compute) |
| seq_len (`max_length`) | 512 |
| batch_size (per device) | 1 |
| grad_accum_steps | 8 (effective batch 8) |
| LoRA r / alpha | 16 / 32, ~9.3M trainable params (1.23% of 762M) |

## Measured

- **VRAM peak: 2794 MB** (`torch.cuda.max_memory_allocated()`), 2 training steps, batch_size=1,
  seq_len cap 512 (actual sequences much shorter — a support ticket + JSON label, ~100-300 tokens).
- That leaves roughly 5GB of headroom on this 8GB card at idle (~371MB already used by
  Windows/other apps outside this process).
- LoRA optimizer state is tiny (9.3M params, AdamW = 2 extra fp32 buffers ≈ 75MB) — VRAM here is
  dominated by the quantized base weights (~0.5GB at 4-bit for an 873M model) and activations, not
  the optimizer. A full 200-row / multi-epoch run should not meaningfully exceed this peak, since
  activation memory scales with `seq_len × batch_size`, not dataset size or epoch count.

## Expected failure mode: CUDA OOM

If VRAM is exceeded, `src/train/run.py` catches `torch.OutOfMemoryError` around `trainer.train()`
and exits non-zero with an explicit, ordered list of which knob to cut first (see the `except`
block): 1) `batch_size` down / `grad_accum_steps` up, 2) `seq_len` down, 3) confirm `quantization:
4bit` is actually active (it falls back to 8bit or fp16 automatically if `bitsandbytes` doesn't
work — see `resolve_quantization`), 4) `lora.r` down. It does not silently retry with different
settings — a rerun with adjusted config is required.

Given the measured 2794MB peak against an 8188MB card, hitting this failure mode with the default
config is unlikely; it becomes relevant if `seq_len` or `batch_size` are raised well above the
current defaults, or if training a larger checkpoint than `Qwen/Qwen3.5-0.8B` (e.g. someone points
`base_model_id` at `qwen3.5:2b`'s HF twin instead).
