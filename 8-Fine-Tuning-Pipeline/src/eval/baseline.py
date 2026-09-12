"""Frozen prompt-only baseline eval. This is the number LoRA training must beat.

`configs/baseline_prompt.txt` is frozen after Phase 3 (typos only) so later phases can't
retroactively flatter the baseline by tuning its prompt. `run_baseline`/`score_one`/
`aggregate_metrics` here are reused as-is by src/eval/bakeoff.py to score the LoRA adapter through
the same code path — open that module next.

CLI: uv run python -m src.eval.baseline --model qwen3.5:0.8b
"""

import argparse
import csv
import json
import logging
from pathlib import Path

from src.data.schema import TicketExample, TicketTarget, load_examples, parse_ticket_target
from src.providers.base import ChatClient
from src.providers.ollama import OllamaTeacher

logger = logging.getLogger(__name__)

FIELDS = ("priority", "product", "sentiment", "next_action")
DEFAULT_PROMPT_FILE = Path("configs/baseline_prompt.txt")
DEFAULT_TEST_FILE = Path("data/processed/test.jsonl")
DEFAULT_REPORT_DIR = Path("reports")


def safe_name(model: str) -> str:
    """Ollama tags contain ':', which Windows filenames can't have."""
    return model.replace(":", "_").replace("/", "_")


# temperature=0.0 is hardcoded here, not a CLI flag — every score_one/run_baseline call in this
# repo (baseline and LoRA alike) is greedy decoding; there is no sampled-eval code path.
def score_one(model: ChatClient, system_prompt: str, gold: TicketTarget, ticket_text: str) -> dict:
    raw = model.chat(system=system_prompt, user=ticket_text, temperature=0.0)
    try:
        pred: TicketTarget | None = parse_ticket_target(raw)
        error = ""
    except ValueError as e:
        pred = None
        error = str(e)

    field_match = {f: pred is not None and getattr(pred, f) == getattr(gold, f) for f in FIELDS}
    return {
        "json_valid": pred is not None,
        "pred": pred,
        "raw": raw,
        "error": error,
        "field_match": field_match,
        "full_exact": all(field_match.values()),
    }


def aggregate_metrics(rows: list[dict]) -> dict:
    """Pure metric computation over already-scored rows (see score_one) — no model calls."""
    # field_micro_f1 is correct-fields / (n_items * 4 fields): since each field is single-label
    # multi-class, micro-precision == micro-recall == this value == flattened per-field accuracy.
    # See docs/EVAL.md for why that equivalence holds.
    n = len(rows)
    json_valid_rate = sum(r["json_valid"] for r in rows) / n if n else 0.0
    full_exact_rate = sum(r["full_exact"] for r in rows) / n if n else 0.0
    correct_fields = sum(sum(r["field_match"].values()) for r in rows)
    micro_f1 = correct_fields / (n * len(FIELDS)) if n else 0.0
    per_field_accuracy = {
        f: (sum(r["field_match"][f] for r in rows) / n if n else 0.0) for f in FIELDS
    }
    return {
        "n_items": n,
        "json_valid_rate": json_valid_rate,
        "field_micro_f1": micro_f1,
        "full_exact_rate": full_exact_rate,
        "per_field_accuracy": per_field_accuracy,
    }


def run_baseline(
    model: ChatClient, examples: list[TicketExample], system_prompt: str
) -> tuple[dict, list[dict]]:
    rows = []
    for i, ex in enumerate(examples):
        result = score_one(model, system_prompt, ex.target, ex.input)
        rows.append({"idx": i, "input": ex.input, "gold": ex.target, **result})

    report = {"model": model.model_name, **aggregate_metrics(rows), "temperature": 0.0}
    return report, rows


def write_report(
    report: dict,
    rows: list[dict],
    out_dir: Path,
    model_name: str,
    prompt_file: Path,
    prefix: str = "baseline",
) -> tuple[Path, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    name = safe_name(model_name)
    report_path = out_dir / f"{prefix}_{name}.json"
    csv_path = out_dir / f"{prefix}_{name}_errors.csv"

    full_report = {**report, "prompt_file": str(prompt_file), "errors_csv": str(csv_path)}
    report_path.write_text(json.dumps(full_report, indent=2), encoding="utf-8")

    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "idx",
                "json_valid",
                "input",
                *[f"gold_{f}" for f in FIELDS],
                *[f"pred_{f}" for f in FIELDS],
                "mismatched_fields",
                "error",
            ]
        )
        for r in rows:
            # Despite the "_errors.csv" name applying to the whole file: only non-exact-match
            # rows are written here. A perfect run produces a header-only CSV, not one row per item.
            if r["full_exact"]:
                continue
            gold, pred = r["gold"], r["pred"]
            mismatched = [f for f in FIELDS if not r["field_match"][f]]
            writer.writerow(
                [
                    r["idx"],
                    r["json_valid"],
                    r["input"],
                    *[getattr(gold, f) for f in FIELDS],
                    *[(getattr(pred, f) if pred is not None else "") for f in FIELDS],
                    ";".join(mismatched),
                    r["error"],
                ]
            )
    return report_path, csv_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="qwen3.5:0.8b")
    parser.add_argument("--test-file", type=Path, default=DEFAULT_TEST_FILE)
    parser.add_argument("--prompt-file", type=Path, default=DEFAULT_PROMPT_FILE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_REPORT_DIR)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    system_prompt = args.prompt_file.read_text(encoding="utf-8")
    examples = load_examples(args.test_file)
    model = OllamaTeacher(args.model)

    report, rows = run_baseline(model, examples, system_prompt)
    report_path, csv_path = write_report(report, rows, args.out_dir, args.model, args.prompt_file)

    logger.info(
        "n=%d json_valid_rate=%.2f field_micro_f1=%.2f full_exact_rate=%.2f",
        report["n_items"], report["json_valid_rate"], report["field_micro_f1"], report["full_exact_rate"],
    )
    logger.info("wrote %s and %s", report_path, csv_path)


if __name__ == "__main__":
    main()
