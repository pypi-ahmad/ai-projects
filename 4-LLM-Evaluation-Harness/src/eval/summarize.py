"""Joins candidates.jsonl + rule_scores.jsonl + judge_scores.jsonl (the last
is optional) against a dataset, and reduces them to a RunSummary: overall,
per-suite, and per-tag n_cases / n_error / mean rule pass rate / mean judge
overall / p95 latency.
"""

import hashlib
import json
import math
from pathlib import Path
from typing import TypedDict

from src.dataset import load_file
from src.eval.models import GroupSummary, RunSummary


class _Row(TypedDict):
    suite: str
    tags: list[str]
    error: bool
    latency_ms: float
    rule_pass_rate: float | None
    judge_overall: float | None


def _percentile(values: list[float], pct: float) -> float | None:
    # Linear interpolation between the two nearest ranks (same convention as
    # numpy's default `interpolation="linear"`), not nearest-rank / step lookup.
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return ordered[int(k)]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def _mean(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    if not present:
        return None
    return sum(present) / len(present)


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _case_rule_pass_rate(metrics: list[dict]) -> float | None:
    # Excludes informational metrics (passed=None, e.g. length/latency) from the
    # denominator -- a case with only those and no expected.* fields set yields
    # None here rather than a misleading 0/0 or 1.0.
    applicable = [m for m in metrics if m.get("passed") is not None]
    if not applicable:
        return None
    return sum(1 for m in applicable if m["passed"]) / len(applicable)


def _summarize_group(rows: list[_Row]) -> GroupSummary:
    return GroupSummary(
        n_cases=len(rows),
        n_error=sum(1 for r in rows if r["error"]),
        mean_rule_pass_rate=_mean([r["rule_pass_rate"] for r in rows]),
        mean_judge_overall=_mean([r["judge_overall"] for r in rows]),
        p95_latency_ms=_percentile([r["latency_ms"] for r in rows], 0.95),
    )


def summarize_run(run_dir: Path, dataset_path: Path) -> RunSummary:
    cases_by_id = {c.id: c for c in load_file(dataset_path)}
    candidates = _read_jsonl(run_dir / "candidates.jsonl")
    rule_scores_by_id = {r["case_id"]: r for r in _read_jsonl(run_dir / "rule_scores.jsonl")}
    judge_scores_by_id = {r["case_id"]: r for r in _read_jsonl(run_dir / "judge_scores.jsonl")}

    rows: list[_Row] = []
    for record in candidates:
        if record.get("skip_reason"):
            continue  # case.skip_if excluded this case from the run entirely
        case = cases_by_id.get(record["case_id"])
        if case is None:
            continue
        rule_score = rule_scores_by_id.get(record["case_id"])
        judge_score = judge_scores_by_id.get(record["case_id"])
        rows.append(
            _Row(
                suite=case.suite,
                tags=case.tags,
                error=record.get("error") is not None,
                latency_ms=record["latency_ms"],
                rule_pass_rate=(
                    _case_rule_pass_rate(rule_score["metrics"]) if rule_score else None
                ),
                judge_overall=(
                    judge_score["overall"]
                    if judge_score and judge_score["status"] == "ok"
                    else None
                ),
            )
        )

    overall = _summarize_group(rows)

    by_suite = {
        suite: _summarize_group([r for r in rows if r["suite"] == suite])
        for suite in sorted({r["suite"] for r in rows})
    }
    all_tags = sorted({tag for r in rows for tag in r["tags"]})
    by_tag = {
        tag: _summarize_group([r for r in rows if tag in r["tags"]]) for tag in all_tags
    }

    dataset_hash = hashlib.sha256(dataset_path.read_bytes()).hexdigest()

    return RunSummary(
        run_id=run_dir.name,
        dataset_path=str(dataset_path),
        dataset_hash=dataset_hash,
        n_cases=overall.n_cases,
        n_error=overall.n_error,
        mean_rule_pass_rate=overall.mean_rule_pass_rate,
        mean_judge_overall=overall.mean_judge_overall,
        p95_latency_ms=overall.p95_latency_ms,
        by_suite=by_suite,
        by_tag=by_tag,
    )


def _fmt_pct(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.1f}%"


def _fmt_ms(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}"


def _table(title: str, groups: dict[str, GroupSummary]) -> list[str]:
    lines = [
        f"## {title}",
        "",
        "| Name | Cases | Errors | Rule pass rate | Judge overall | p95 latency (ms) |",
        "|---|---|---|---|---|---|",
    ]
    for name, g in groups.items():
        lines.append(
            f"| {name} | {g.n_cases} | {g.n_error} | {_fmt_pct(g.mean_rule_pass_rate)} | "
            f"{_fmt_pct(g.mean_judge_overall)} | {_fmt_ms(g.p95_latency_ms)} |"
        )
    lines.append("")
    return lines


def render_markdown(summary: RunSummary) -> str:
    lines = [
        f"# Run Summary: {summary.run_id}",
        "",
        f"- Dataset: `{summary.dataset_path}` (`{summary.dataset_hash[:12]}`)",
        f"- Cases: {summary.n_cases} ({summary.n_error} errors)",
        f"- Mean rule pass rate: {_fmt_pct(summary.mean_rule_pass_rate)}",
        f"- Mean judge overall: {_fmt_pct(summary.mean_judge_overall)}",
        f"- p95 latency: {_fmt_ms(summary.p95_latency_ms)} ms",
        "",
    ]
    lines += _table("By suite", summary.by_suite)
    lines += _table("By tag", summary.by_tag)
    return "\n".join(lines)
