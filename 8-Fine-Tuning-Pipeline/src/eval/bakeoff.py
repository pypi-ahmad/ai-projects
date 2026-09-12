"""LoRA vs the frozen prompt-only baseline. Same test set, same decoding settings, same metrics.
Must not retrain or modify the adapter — read-only consumer of outputs/adapters/<run_id>/. Open
src/ui/app.py next; it renders this module's reports/bakeoff.md output.

CLI: uv run python -m src.eval.bakeoff --adapter outputs/adapters/<run_id> \
        --baseline reports/baseline_qwen3.5_0.8b.json
Optional judge on disagreements only (off by default): add --judge
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Literal

import torch
from peft import PeftModel
from pydantic import BaseModel
from transformers import AutoModelForCausalLM, AutoTokenizer

from src.data.schema import TicketExample, TicketTarget, load_examples, parse_ticket_target
from src.eval.baseline import (
    DEFAULT_PROMPT_FILE,
    DEFAULT_TEST_FILE,
    FIELDS,
    aggregate_metrics,
    run_baseline,
    write_report,
)
from src.providers import get_teacher
from src.train.run import resolve_quantization

logger = logging.getLogger(__name__)

DEFAULT_REPORT_DIR = Path("reports")
DEFAULT_BASELINE_2B = Path("reports/baseline_qwen3.5_2b.json")
# Ollama's baseline call left num_predict unbounded (default); local generate() requires an
# explicit cap. 200 tokens is generous headroom for the ~4-field JSON schema — documented
# assumption, not a silent guess. See docs/EVAL.md.
MAX_NEW_TOKENS = 200


class JudgeVerdict(BaseModel):
    winner: Literal["baseline", "lora", "tie"]


class LocalAdapterModel:
    """Base model + LoRA adapter. Exposes the same ChatClient shape as OllamaTeacher so it plugs
    straight into src.eval.baseline.run_baseline without changes to the scoring code."""

    def __init__(
        self, base_model_id: str, adapter_dir: Path, max_new_tokens: int = MAX_NEW_TOKENS
    ) -> None:
        self.model_name = f"{base_model_id}+lora:{Path(adapter_dir).name}"
        self.max_new_tokens = max_new_tokens
        self.tokenizer = AutoTokenizer.from_pretrained(base_model_id)

        # Always probes for "4bit" here regardless of what train_meta.json's "quantization" field
        # recorded for this adapter. If the adapter was actually trained in the fp16 fallback mode,
        # this reloads the base model at a different precision than it was trained at.
        _, _, _, bnb_config = resolve_quantization("4bit", seq_len=512, batch_size=1)
        model_kwargs: dict = {"dtype": torch.bfloat16, "attn_implementation": "sdpa"}
        if bnb_config is not None:
            model_kwargs["quantization_config"] = bnb_config
            model_kwargs["device_map"] = {"": 0}
        base_model = AutoModelForCausalLM.from_pretrained(base_model_id, **model_kwargs)
        if bnb_config is None:
            base_model.to("cuda" if torch.cuda.is_available() else "cpu")

        self.model = PeftModel.from_pretrained(base_model, adapter_dir)
        self.model.eval()

    def chat(self, system: str, user: str, temperature: float = 0.0) -> str:
        # `temperature` is accepted for ChatClient compatibility but not read below — generation
        # is always greedy (do_sample=False); a non-zero value here has no effect.
        # Applies the tokenizer's chat template client-side, unlike OllamaTeacher.chat (see its
        # comment), which sends the same two strings to Ollama and lets the server template them.
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        inputs = self.tokenizer.apply_chat_template(
            messages, add_generation_prompt=True, return_tensors="pt", return_dict=True
        ).to(self.model.device)
        with torch.no_grad():
            out = self.model.generate(
                **inputs, max_new_tokens=self.max_new_tokens, do_sample=False
            )
        completion = out[0][inputs["input_ids"].shape[1] :]
        return self.tokenizer.decode(completion, skip_special_tokens=True)


def find_disagreements(baseline_rows: list[dict], lora_rows: list[dict]) -> list[int]:
    """Indices where baseline's and lora's predictions differ from each other."""
    idxs = []
    # strict=True: both row lists must be the same length. Holds as long as both were produced by
    # run_baseline over the same `examples` list (see main()) — not enforced beyond that.
    for b, la in zip(baseline_rows, lora_rows, strict=True):
        b_pred = b["pred"].model_dump() if b["pred"] is not None else None
        l_pred = la["pred"].model_dump() if la["pred"] is not None else None
        if b_pred != l_pred:
            idxs.append(b["idx"])
    return idxs


JUDGE_PROMPT = """You are judging a disagreement between two models on a support-ticket
classification task. Given the ticket, the correct (gold) label, and each model's prediction,
decide which prediction is closer to the gold label overall. Return ONLY a single JSON object
with exactly one key: {{"winner": "baseline"}} or {{"winner": "lora"}} or {{"winner": "tie"}}.

Ticket: {ticket}
Gold label: {gold}
Baseline prediction: {baseline_pred}
LoRA prediction: {lora_pred}"""


def judge_one(
    judge_model_name: str, ticket: str, gold: dict, baseline_pred: dict | None, lora_pred: dict | None
) -> JudgeVerdict:
    judge = get_teacher(judge_model_name)
    prompt = JUDGE_PROMPT.format(
        ticket=ticket, gold=gold, baseline_pred=baseline_pred, lora_pred=lora_pred
    )
    raw = judge.complete(prompt)
    try:
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`")
            text = text[4:].strip() if text.lower().startswith("json") else text.strip()
        return JudgeVerdict.model_validate(json.loads(text))
    except Exception as e:  # noqa: BLE001 - a broken judge reply is a tie, not a crash
        logger.warning("judge reply unparseable, counting as tie: %s", e)
        return JudgeVerdict(winner="tie")


def run_judge(
    judge_model_name: str, baseline_rows: list[dict], lora_rows: list[dict]
) -> dict:
    disagreement_idxs = find_disagreements(baseline_rows, lora_rows)
    by_idx = {r["idx"]: r for r in lora_rows}
    verdicts = {"baseline": 0, "lora": 0, "tie": 0}
    for idx in disagreement_idxs:
        b, la = next(r for r in baseline_rows if r["idx"] == idx), by_idx[idx]
        pred_b = b["pred"].model_dump() if b["pred"] is not None else None
        pred_l = la["pred"].model_dump() if la["pred"] is not None else None
        verdict = judge_one(judge_model_name, b["input"], b["gold"].model_dump(), pred_b, pred_l)
        verdicts[verdict.winner] += 1
    return {
        "judge_model": judge_model_name,
        "n_disagreements": len(disagreement_idxs),
        "verdicts": verdicts,
    }


def _fmt_delta(delta: float) -> str:
    sign = "+" if delta >= 0 else ""
    return f"{sign}{delta:.3f}"


def write_bakeoff_md(
    out_path: Path,
    baseline_report: dict,
    baseline_2b_report: dict | None,
    lora_report: dict,
    judge_result: dict | None,
) -> None:
    metrics = ("json_valid_rate", "field_micro_f1", "full_exact_rate")
    lines = ["# Bake-off: LoRA vs frozen prompt-only baseline", ""]

    header = ["Metric", "baseline (0.8b)"]
    if baseline_2b_report is not None:
        header.append("baseline (2b)")
    header += ["lora (0.8b)", "delta (lora - baseline 0.8b)"]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "---|" * len(header))

    deltas = {}
    for m in metrics:
        delta = lora_report[m] - baseline_report[m]
        deltas[m] = delta
        row = [m, f"{baseline_report[m]:.3f}"]
        if baseline_2b_report is not None:
            row.append(f"{baseline_2b_report[m]:.3f}")
        row += [f"{lora_report[m]:.3f}", _fmt_delta(delta)]
        lines.append("| " + " | ".join(row) + " |")

    lines += ["", f"n_items: baseline={baseline_report['n_items']}, lora={lora_report['n_items']}", ""]

    lines.append("## Verdict")
    lines.append("")
    any_loss = False
    # The 1e-9 threshold below is float-equality noise guarding, not a meaningful tolerance band —
    # any real delta is expected to be far larger than this.
    for m in metrics:
        d = deltas[m]
        if d > 1e-9:
            lines.append(f"- LoRA **improved** `{m}`: {baseline_report[m]:.3f} -> {lora_report[m]:.3f} ({_fmt_delta(d)}).")
        elif d < -1e-9:
            lines.append(f"- LoRA **regressed** on `{m}`: {baseline_report[m]:.3f} -> {lora_report[m]:.3f} ({_fmt_delta(d)}).")
            any_loss = True
        else:
            lines.append(f"- LoRA **unchanged** on `{m}`: {baseline_report[m]:.3f}.")

    if deltas["full_exact_rate"] <= 1e-9:
        lines.append("")
        lines.append(
            "**LoRA did NOT beat the frozen baseline** on the primary metric (`full_exact_rate`). "
            "This is a real result, not a formatting error — see the per-item CSVs in `reports/` "
            "for where it failed."
        )
    elif any_loss:
        lines.append("")
        lines.append(
            "LoRA beat the baseline on `full_exact_rate` overall, but regressed on at least one "
            "other metric above — not a clean sweep."
        )

    if judge_result is not None:
        lines += ["", "## Judge (on disagreements only)", ""]
        lines.append(f"Judge model: `{judge_result['judge_model']}`")
        lines.append(f"Disagreements between baseline and lora: {judge_result['n_disagreements']}")
        v = judge_result["verdicts"]
        lines.append(f"Verdicts: baseline={v['baseline']}, lora={v['lora']}, tie={v['tie']}")

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_adapter_missing_md(out_path: Path, adapter_path: Path) -> None:
    """Training was never run (no adapter dir / no train_meta.json). Say so plainly instead of
    producing a table of fabricated or degenerate scores."""
    text = (
        "# Bake-off: LoRA vs frozen prompt-only baseline\n\n"
        f"**adapter missing** — no `train_meta.json` found under `{adapter_path}`.\n\n"
        "Training has not been run in this environment. Run `train.cmd` "
        "(or `train.cmd --config configs\\train_smoke.yaml` for a 2-step smoke test), "
        "then re-run `python -m src.eval.bakeoff`.\n"
    )
    out_path.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--baseline-2b", type=Path, default=DEFAULT_BASELINE_2B)
    parser.add_argument("--test-file", type=Path, default=DEFAULT_TEST_FILE)
    parser.add_argument("--prompt-file", type=Path, default=DEFAULT_PROMPT_FILE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--judge", action="store_true", help="off by default")
    parser.add_argument("--judge-model", default="granite4.1:3b")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    train_meta_path = args.adapter / "train_meta.json"
    if not train_meta_path.exists():
        logger.error("adapter missing: no train_meta.json under %s", args.adapter)
        args.out_dir.mkdir(parents=True, exist_ok=True)
        write_adapter_missing_md(args.out_dir / "bakeoff.md", args.adapter)
        sys.exit(1)

    baseline_report = json.loads(args.baseline.read_text(encoding="utf-8"))
    baseline_2b_report = (
        json.loads(args.baseline_2b.read_text(encoding="utf-8")) if args.baseline_2b.exists() else None
    )

    train_meta = json.loads(train_meta_path.read_text(encoding="utf-8"))
    base_model_id = train_meta["base_model_id"]
    run_id = train_meta["run_id"]

    system_prompt = args.prompt_file.read_text(encoding="utf-8")
    examples = load_examples(args.test_file)

    lora_model = LocalAdapterModel(base_model_id, args.adapter)
    lora_report, lora_rows = run_baseline(lora_model, examples, system_prompt)
    lora_report_path, lora_csv_path = write_report(
        lora_report, lora_rows, args.out_dir, run_id, args.prompt_file, prefix="lora"
    )
    logger.info(
        "lora n=%d json_valid_rate=%.2f field_micro_f1=%.2f full_exact_rate=%.2f",
        lora_report["n_items"], lora_report["json_valid_rate"],
        lora_report["field_micro_f1"], lora_report["full_exact_rate"],
    )
    logger.info("wrote %s and %s", lora_report_path, lora_csv_path)

    judge_result = None
    if args.judge:
        # The saved baseline_*.json only has aggregate metrics, not per-item predictions, so the
        # judge needs those regenerated. Baseline runs at temperature 0 (greedy), so re-running it
        # in-process against the same test set reproduces the same predictions used for `--baseline`.
        from src.providers.ollama import OllamaTeacher

        baseline_model_tag = baseline_report["model"]
        baseline_model = OllamaTeacher(baseline_model_tag)
        _, baseline_rows = run_baseline(baseline_model, examples, system_prompt)
        judge_result = run_judge(args.judge_model, baseline_rows, lora_rows)
        (args.out_dir / f"judge_{run_id}.json").write_text(
            json.dumps(judge_result, indent=2), encoding="utf-8"
        )

    write_bakeoff_md(
        args.out_dir / "bakeoff.md", baseline_report, baseline_2b_report, lora_report, judge_result
    )
    logger.info("wrote %s", args.out_dir / "bakeoff.md")


if __name__ == "__main__":
    main()
