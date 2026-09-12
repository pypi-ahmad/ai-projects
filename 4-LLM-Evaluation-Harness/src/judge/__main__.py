"""Runs the LLM-as-judge pipeline over a candidates.jsonl, scoring each case
that requests judging (case.judge is set) against a named rubric.
"""

import argparse
import json
import sys
from pathlib import Path

from src.dataset import load_file
from src.judge.pipeline import judge_case
from src.judge.rubric import load_rubric
from src.providers import PROVIDERS
from src.providers.base import ProviderConfigError, Unloadable

DEFAULT_RUBRICS_DIR = Path("rubrics")


def _load_candidates(path: Path) -> list[dict]:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.judge")
    parser.add_argument("--candidates", type=Path, required=True, help="candidates.jsonl path")
    parser.add_argument("--dataset", type=Path, required=True, help="Golden *.jsonl file")
    parser.add_argument("--provider", required=True, choices=sorted(PROVIDERS))
    parser.add_argument("--model", required=True)
    parser.add_argument("--rubric", required=True, help="Rubric id, e.g. answer_quality")
    parser.add_argument("--rubrics-dir", type=Path, default=DEFAULT_RUBRICS_DIR)
    parser.add_argument(
        "--out", type=Path, default=None, help="Default: <candidates dir>/judge_scores.jsonl"
    )
    args = parser.parse_args(argv)

    spec = PROVIDERS[args.provider]
    if args.model not in spec.allowed_models:
        print(
            f"model {args.model!r} is not allowed for provider {args.provider!r}; "
            f"choose one of {spec.allowed_models}",
            file=sys.stderr,
        )
        return 1

    try:
        judge_provider = spec.factory()
    except ProviderConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    try:
        rubric = load_rubric(args.rubrics_dir, args.rubric)
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    cases_by_id = {case.id: case for case in load_file(args.dataset)}
    candidates = _load_candidates(args.candidates)

    out_path = args.out or (args.candidates.parent / "judge_scores.jsonl")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    any_same_model_warning = False
    with out_path.open("w", encoding="utf-8") as fh:
        for record in candidates:
            case = cases_by_id.get(record["case_id"])
            if case is None:
                print(
                    f"warning: no dataset case for candidate id {record['case_id']!r}, skipping",
                    file=sys.stderr,
                )
                continue
            if record.get("text") is None:
                continue  # nothing to judge -- the candidate call itself failed

            judge_record = judge_case(
                case,
                candidate_text=record["text"],
                rubric=rubric,
                judge_provider=judge_provider,
                judge_provider_name=args.provider,
                judge_model=args.model,
                candidate_provider_name=record["provider"],
                candidate_model=record["model"],
            )
            if judge_record is None:
                continue
            if judge_record.same_model_warning:
                any_same_model_warning = True
            fh.write(judge_record.model_dump_json() + "\n")
            written += 1

    if any_same_model_warning:
        print(
            "warning: judge model is the same as the candidate model for at least one case "
            "-- scores may be biased (self-judging)",
            file=sys.stderr,
        )

    if args.provider == "ollama" and isinstance(judge_provider, Unloadable):
        judge_provider.unload(args.model)

    print(f"Wrote {written} judge score(s) to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
