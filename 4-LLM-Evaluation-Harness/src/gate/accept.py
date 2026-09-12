"""Builds and writes a Baseline from an already-summarized run directory.
Shared by the `--accept` CLI mode and the Streamlit "write local baseline"
button -- both are local-only actions, never something CI calls.
"""

import json
from pathlib import Path

from src.eval.models import RunSummary
from src.gate.models import Baseline, BaselineConfig

DEFAULT_BASELINE_PATH = Path("baselines/current.json")


def _first_record(path: Path) -> dict | None:
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            return json.loads(line)
    return None


def build_baseline(run_dir: Path) -> Baseline:
    summary_path = run_dir / "summary.json"
    if not summary_path.exists():
        raise FileNotFoundError(f"no summary.json in {run_dir} -- run src.eval first")
    summary = RunSummary.model_validate_json(summary_path.read_text(encoding="utf-8"))

    candidate_record = _first_record(run_dir / "candidates.jsonl")
    judge_record = _first_record(run_dir / "judge_scores.jsonl")

    config = BaselineConfig(
        candidate_provider=candidate_record.get("provider") if candidate_record else None,
        candidate_model=candidate_record.get("model") if candidate_record else None,
        judge_provider=judge_record.get("judge_provider") if judge_record else None,
        judge_model=judge_record.get("judge_model") if judge_record else None,
        dataset_path=summary.dataset_path,
        dataset_hash=summary.dataset_hash,
    )
    return Baseline(summary=summary, config=config)


def write_baseline(baseline: Baseline, path: Path = DEFAULT_BASELINE_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(baseline.model_dump_json(indent=2), encoding="utf-8")
    return path
