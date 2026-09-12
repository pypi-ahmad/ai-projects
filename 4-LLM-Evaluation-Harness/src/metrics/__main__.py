"""Joins a candidates.jsonl (from src.runners.candidate) against its golden
dataset file and writes one rule-based CaseScore per candidate record.
"""

import argparse
import json
import sys
from pathlib import Path

from src.dataset import load_file
from src.metrics.aggregate import score_case


def _load_candidates(path: Path) -> list[dict]:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.metrics")
    parser.add_argument("--candidates", type=Path, required=True, help="candidates.jsonl path")
    parser.add_argument("--dataset", type=Path, required=True, help="Golden *.jsonl file")
    parser.add_argument("--out", type=Path, required=True, help="Where to write rule_scores.jsonl")
    args = parser.parse_args(argv)

    cases_by_id = {case.id: case for case in load_file(args.dataset)}
    candidates = _load_candidates(args.candidates)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with args.out.open("w", encoding="utf-8") as fh:
        for record in candidates:
            case = cases_by_id.get(record["case_id"])
            if case is None:
                print(
                    f"warning: no dataset case for candidate id {record['case_id']!r}, skipping",
                    file=sys.stderr,
                )
                continue
            if record.get("skip_reason"):
                continue  # case.skip_if excluded this case from the run entirely
            score = score_case(case, text=record.get("text"), latency_ms=record["latency_ms"])
            fh.write(score.model_dump_json() + "\n")
            written += 1

    print(f"Wrote {written} score(s) to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
