# Budget Policy

## Token budget anatomy

```
context_window  (from model_windows.yaml or caller-supplied)
├── output_reserve     policy.output_pct × window   → tokens for model generation; never packed
├── system_reserve     policy.system_pct × window   → additional system headroom (default 8%)
├── user_message       counted at runtime            → always kept; never packed
└── usable budget      remainder after the three slots above
    ├── memory cap     policy.caps.memory × usable
    ├── docs cap       policy.caps.docs   × usable
    └── tools cap      policy.caps.tools  × usable
```

Caps are **soft** upper bounds enforced per family in Pass B; unclaimed cap is available to other
families in Pass C (borrow step).

`system` and `user` family blocks are force-kept before the pack loop and do **not** consume the
usable budget counter. Size them at the caller's discretion.

## Built-in policies

Defined in `config/policies/*.yaml`. All policies set `output_pct=0.20` and `system_pct=0.08`
unless overridden.

| Policy | memory | docs | tools |
|--------|--------|------|-------|
| `balanced` | 0.30 | 0.45 | 0.25 |
| `docs_heavy` | 0.15 | 0.70 | 0.15 |
| `tools_heavy` | 0.20 | 0.25 | 0.55 |
| `memory_heavy` | 0.55 | 0.30 | 0.15 |

Cap fractions must sum to 1.0 (enforced at load time).

## Example at 8 192 tokens (balanced policy)

| Slot | Value | Tokens |
|------|-------|--------|
| output_reserve | 20% | 1 638 |
| system_reserve | 8% | 655 |
| user_message | counted | ~10 to 50 |
| usable | ~72% | ~5 900 |
| memory cap | 30% of usable | ~1 770 |
| docs cap | 45% of usable | ~2 655 |
| tools cap | 25% of usable | ~1 475 |

## Overflow policy

1. **Pack in priority order** within each family cap.
2. **Block doesn't fit and `compressible=True`**: create a `CompressJob` with `target_tokens = usable − tokens_used_so_far` (the space remaining at the moment the job is created); run `run_compress_jobs()` after allocation.
3. **Block doesn't fit and `compressible=False`**: drop immediately.
4. **Every dropped or compress-job block** records a `DropRecord` with a `DropReason`.

## Drop reasons

| Reason | When |
|--------|------|
| `EMPTY_TEXT` | `block.text.strip()` is empty |
| `OVER_FAMILY_CAP` | Family cap and borrow pool exhausted |
| `OVER_WINDOW` | Global usable budget exhausted |
| `ZERO_PRIORITY` | `block.priority == 0` and no space |
| `RESERVE` | Defined in enum; not currently triggered (system/user blocks are always force-kept) |
| `COMPRESS_UNAVAILABLE` | Compress attempted; all providers returned `None` |
| `COMPRESS_FAILED` | Provider returned text ≥ original length |

## Compress-job outcomes

`run_compress_jobs()` in `src/compress/compressor.py`.

| Flag | Condition | Disposition |
|------|-----------|-------------|
| `OK` | Provider returned shorter text within target | Block kept |
| `TRIMMED` | Compressed text still over target; sentence-trimmed | Block kept |
| `COMPRESS_FAILED` | Provider returned text ≥ original | Block dropped |
| `COMPRESS_UNAVAILABLE` | All providers returned `None` | Block dropped |

### Offline guarantee

If no provider key is set and Ollama is unreachable, `compress_one()` returns
`COMPRESS_UNAVAILABLE` and `run_compress_jobs()` moves the block to `dropped`. Packing always
completes without raising an exception.

### Model unload

After each batch, `run_compress_jobs()` calls `ollama_unload(model)` (`keep_alive=0`), releasing
VRAM. Pass `unload_after=False` in tests or when chaining batches immediately.

## Changing defaults

Edit `config/policies/<name>.yaml` or create a new file. Pass the policy name in
`ContextRequest.policy`. Caps must sum to 1.0; `output_pct` + `system_pct` apply to the full
`context_window` before the usable budget is computed.
