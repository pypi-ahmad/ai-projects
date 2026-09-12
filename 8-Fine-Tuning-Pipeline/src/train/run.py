"""LoRA/QLoRA training driven by configs/train.yaml. Adapter-only save, no merging. Open
src/eval/bakeoff.py next — it loads exactly what main() writes to outputs/adapters/<run_id>/.

CLI: uv run python -m src.train.run --config configs/train.yaml
Dry-run smoke: uv run python -m src.train.run --config configs/train.yaml --max-steps 2
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import torch
import yaml
from datasets import Dataset
from peft import LoraConfig, TaskType, prepare_model_for_kbit_training
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from trl import SFTConfig, SFTTrainer

from src.data.schema import load_examples

logger = logging.getLogger(__name__)


def probe_bnb_4bit() -> bool:
    if not torch.cuda.is_available():
        return False
    try:
        import bitsandbytes as bnb

        layer = bnb.nn.Linear4bit(8, 8, compute_dtype=torch.bfloat16).to("cuda")
        layer(torch.randn(1, 8, dtype=torch.bfloat16, device="cuda"))
        return True
    except Exception as e:  # noqa: BLE001 - any failure here means "can't use it"
        logger.warning("4-bit bitsandbytes probe failed: %s", e)
        return False


def probe_bnb_8bit() -> bool:
    if not torch.cuda.is_available():
        return False
    try:
        import bitsandbytes as bnb

        layer = bnb.nn.Linear8bitLt(8, 8, has_fp16_weights=False).to("cuda")
        layer(torch.randn(1, 8, device="cuda").half())
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("8-bit bitsandbytes probe failed: %s", e)
        return False


def resolve_quantization(
    preferred: str, seq_len: int, batch_size: int
) -> tuple[str, int, int, BitsAndBytesConfig | None]:
    """Probe what this machine can actually do; downgrade from the config's preference if needed."""
    if preferred == "4bit" and probe_bnb_4bit():
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
        )
        return "4bit", seq_len, batch_size, bnb_config

    logger.warning("4-bit unavailable (or not requested) — trying 8-bit")
    if probe_bnb_8bit():
        return "8bit", seq_len, batch_size, BitsAndBytesConfig(load_in_8bit=True)

    logger.warning("8-bit unavailable — falling back to plain fp16 LoRA (seq_len=256, batch_size=1)")
    return "fp16", min(seq_len, 256), 1, None


def build_dataset(jsonl_path: Path, system_prompt: str) -> Dataset:
    """TRL prompt/completion conversational format. Deliberately not the plain `messages` format:
    Qwen3.5's chat template has no `{% generation %}` marker, so TRL's `assistant_only_loss`
    (which needs that marker) silently produces an all-masked, zero-loss batch. `completion_only_loss`
    on a prompt/completion split works instead, since TRL derives the mask by diffing tokenized
    prompt vs prompt+completion, not from template markup. Verified live before writing this file.
    """
    examples = load_examples(jsonl_path)
    rows = [
        {
            "prompt": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": ex.input},
            ],
            "completion": [
                {"role": "assistant", "content": json.dumps(ex.target.model_dump())},
            ],
        }
        for ex in examples
    ]
    return Dataset.from_list(rows)


def load_config(path: Path) -> dict:
    with Path(path).open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/train.yaml"))
    parser.add_argument("--max-steps", type=int, default=None, help="dry-run smoke: cap training steps")
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    cfg = load_config(args.config)
    # CLI --max-steps wins if given; otherwise fall back to the config file's own max_steps
    # (configs/train_smoke.yaml sets this so a smoke run needs no extra flag).
    max_steps = args.max_steps if args.max_steps is not None else cfg.get("max_steps")
    run_id = args.run_id or time.strftime("%Y%m%d-%H%M%S")
    out_dir = Path(cfg["output_dir"]) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    seq_len = cfg.get("seq_len", 512)
    batch_size = cfg.get("batch_size", 1)
    mode, seq_len, batch_size, bnb_config = resolve_quantization(
        cfg.get("quantization", "4bit"), seq_len, batch_size
    )
    logger.info("quantization mode: %s (seq_len=%d, batch_size=%d)", mode, seq_len, batch_size)

    # Load base model at the resolved quantization, then wrap it in LoRA.
    base_model_id = cfg["base_model_id"]
    tokenizer = AutoTokenizer.from_pretrained(base_model_id)

    model_kwargs: dict = {"dtype": torch.bfloat16, "attn_implementation": "sdpa"}
    if bnb_config is not None:
        model_kwargs["quantization_config"] = bnb_config
        model_kwargs["device_map"] = {"": 0}
    model = AutoModelForCausalLM.from_pretrained(base_model_id, **model_kwargs)

    if bnb_config is not None:
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    else:
        model.to("cuda" if torch.cuda.is_available() else "cpu")
        model.gradient_checkpointing_enable()

    lora_cfg = cfg["lora"]
    peft_config = LoraConfig(
        r=lora_cfg.get("r", 16),
        lora_alpha=lora_cfg.get("alpha", 32),
        lora_dropout=lora_cfg.get("dropout", 0.05),
        target_modules=lora_cfg["target_modules"],
        task_type=TaskType.CAUSAL_LM,
        bias="none",
    )

    # Build datasets, then work out how many steps this run will actually take (needed because
    # SFTConfig below wants an absolute warmup_steps count, not a ratio).
    system_prompt = Path(cfg["prompt_file"]).read_text(encoding="utf-8")
    train_dataset = build_dataset(Path(cfg["train_file"]), system_prompt)
    val_path = Path(cfg["val_file"])
    eval_dataset = build_dataset(val_path, system_prompt) if val_path.exists() else None

    # This trl/transformers pair's SFTConfig takes warmup_steps, not warmup_ratio; convert.
    grad_accum_steps = cfg.get("grad_accum_steps", 8)
    epochs = cfg.get("epochs", 3)
    if max_steps:
        total_steps = max_steps
    else:
        steps_per_epoch = max(1, len(train_dataset) // (batch_size * grad_accum_steps))
        total_steps = steps_per_epoch * epochs
    warmup_ratio = cfg.get("warmup_ratio", 0.03)
    warmup_steps = max(0, int(total_steps * warmup_ratio))

    sft_args = SFTConfig(
        output_dir=str(out_dir / "checkpoints"),
        per_device_train_batch_size=batch_size,
        gradient_accumulation_steps=grad_accum_steps,
        num_train_epochs=epochs,
        learning_rate=float(cfg.get("learning_rate", 2e-4)),
        warmup_steps=warmup_steps,
        max_length=seq_len,
        packing=False,
        completion_only_loss=True,
        dataloader_num_workers=0,  # Windows: worker subprocesses are unreliable/slow here
        logging_steps=1,
        save_strategy="no",  # no intermediate Trainer checkpoints; only the final adapter is saved
        report_to="none",
        max_steps=max_steps if max_steps else -1,
        eval_strategy="epoch" if eval_dataset is not None else "no",
    )

    trainer = SFTTrainer(
        model=model,
        args=sft_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        peft_config=peft_config,
    )

    # Train, tracking peak VRAM for train_meta.json below.
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()

    try:
        result = trainer.train()
    except torch.OutOfMemoryError:
        logger.error(
            "CUDA OOM during training. Cut, in this order: "
            "1) batch_size down / grad_accum_steps up (currently batch_size=%d, grad_accum=%d), "
            "2) seq_len down (currently %d), "
            "3) quantization to 4bit if not already active (currently %s), "
            "4) lora.r down (currently %d).",
            batch_size, grad_accum_steps, seq_len, mode, lora_cfg.get("r", 16),
        )
        sys.exit(1)

    vram_peak_mb = (
        torch.cuda.max_memory_allocated() / (1024 * 1024) if torch.cuda.is_available() else None
    )

    # Persist: adapter weights + tokenizer + the config/results actually used (train_meta.json).
    adapter_dir = out_dir
    trainer.model.save_pretrained(adapter_dir)  # PeftModel.save_pretrained = adapter-only, by design
    tokenizer.save_pretrained(adapter_dir)

    meta = {
        "run_id": run_id,
        "base_model_id": base_model_id,
        "quantization": mode,
        "lora": {
            "r": peft_config.r,
            "alpha": peft_config.lora_alpha,
            "dropout": peft_config.lora_dropout,
            "target_modules": sorted(peft_config.target_modules),
        },
        "seq_len": seq_len,
        "batch_size": batch_size,
        "grad_accum_steps": grad_accum_steps,
        "learning_rate": float(cfg.get("learning_rate", 2e-4)),
        "epochs": epochs,
        "warmup_ratio": warmup_ratio,
        "warmup_steps": warmup_steps,
        "dry_run": max_steps is not None,
        "max_steps_arg": max_steps,
        "num_train_examples": len(train_dataset),
        "num_val_examples": len(eval_dataset) if eval_dataset is not None else 0,
        "steps": result.global_step,
        "final_loss": result.training_loss,
        "vram_peak_mb": vram_peak_mb,
        "adapter_dir": str(adapter_dir),
    }
    (adapter_dir / "train_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    logger.info(
        "steps=%d final_loss=%.4f vram_peak_mb=%s",
        result.global_step, result.training_loss, vram_peak_mb,
    )
    logger.info("wrote adapter + train_meta.json to %s", adapter_dir)


if __name__ == "__main__":
    main()
