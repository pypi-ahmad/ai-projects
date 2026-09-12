"""Streamlit UI: pick a dataset + candidate/judge provider, run it
in-process (reusing the same runner/metrics/judge/eval functions as the
CLIs), see per-case scores and judge rationale, and compare against the
local baseline. Writing a new local baseline is gated behind an explicit
confirmation -- this button is local-only, CI must never call it.
"""

import sys
from pathlib import Path

# Guarantees `from src... import ...` resolves regardless of whether this
# script is launched via `streamlit run src/ui/app.py` (script-dir on
# sys.path) or `python -m streamlit run ...` (repo root on sys.path).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import json  # noqa: E402

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from src.dataset import load_file  # noqa: E402
from src.eval.summarize import summarize_run  # noqa: E402
from src.gate.accept import DEFAULT_BASELINE_PATH, build_baseline, write_baseline  # noqa: E402
from src.gate.models import Baseline  # noqa: E402
from src.judge.pipeline import judge_case  # noqa: E402
from src.judge.rubric import load_rubric  # noqa: E402
from src.metrics import score_case  # noqa: E402
from src.providers import PROVIDERS  # noqa: E402
from src.providers.base import ProviderConfigError  # noqa: E402
from src.runners.candidate import run_candidate  # noqa: E402

DATASET_DIR = Path("datasets/golden")
RUBRICS_DIR = Path("rubrics")
REPORTS_DIR = Path("reports")

st.set_page_config(page_title="LLM Evaluation Harness", layout="wide")
st.title("LLM Evaluation Harness")

with st.sidebar:
    st.header("Run configuration")
    dataset_files = sorted(DATASET_DIR.glob("*.jsonl"))
    if not dataset_files:
        st.error(f"No datasets found under {DATASET_DIR}")
        st.stop()
    dataset_path = st.selectbox("Dataset", dataset_files, format_func=lambda p: p.name)

    candidate_provider = st.selectbox("Candidate provider", sorted(PROVIDERS))
    candidate_model = st.selectbox("Candidate model", PROVIDERS[candidate_provider].allowed_models)

    judge_enabled = st.checkbox("Run judge")
    judge_provider = judge_model = rubric_id = None
    if judge_enabled:
        judge_provider = st.selectbox("Judge provider", sorted(PROVIDERS), key="judge_provider")
        judge_model = st.selectbox(
            "Judge model", PROVIDERS[judge_provider].allowed_models, key="judge_model"
        )
        rubric_ids = [p.stem for p in sorted(RUBRICS_DIR.glob("*.yaml"))]
        rubric_id = st.selectbox("Rubric", rubric_ids)

    run_clicked = st.button("Run evaluation", type="primary")

if run_clicked:
    try:
        candidates_path = run_candidate(
            dataset_path=dataset_path,
            provider_name=candidate_provider,
            model=candidate_model,
            out_dir=REPORTS_DIR,
        )
    except ProviderConfigError as exc:
        st.error(str(exc))
        st.stop()

    run_dir = candidates_path.parent
    cases_by_id = {c.id: c for c in load_file(dataset_path)}
    candidate_records = [
        json.loads(line) for line in candidates_path.read_text(encoding="utf-8").splitlines()
    ]

    judge_provider_instance = rubric = None
    if judge_enabled:
        assert judge_provider is not None
        assert judge_model is not None
        assert rubric_id is not None
        try:
            judge_provider_instance = PROVIDERS[judge_provider].factory()
        except ProviderConfigError as exc:
            st.error(str(exc))
            st.stop()
        rubric = load_rubric(RUBRICS_DIR, rubric_id)

    rule_lines: list[str] = []
    judge_lines: list[str] = []
    rows: list[dict] = []
    progress = st.progress(0.0, text="Scoring cases...")
    for i, record in enumerate(candidate_records):
        case = cases_by_id[record["case_id"]]
        rule_score = score_case(case, text=record["text"], latency_ms=record["latency_ms"])
        rule_lines.append(rule_score.model_dump_json())

        judge_record = None
        if judge_enabled and record["text"] is not None:
            assert judge_provider_instance is not None
            assert judge_provider is not None
            assert judge_model is not None
            assert rubric is not None
            judge_record = judge_case(
                case,
                candidate_text=record["text"],
                rubric=rubric,
                judge_provider=judge_provider_instance,
                judge_provider_name=judge_provider,
                judge_model=judge_model,
                candidate_provider_name=record["provider"],
                candidate_model=record["model"],
            )
            if judge_record is not None:
                judge_lines.append(judge_record.model_dump_json())

        rows.append(
            {
                "case_id": case.id,
                "suite": case.suite,
                "answer": record["text"] or f"[error] {record['error']}",
                "rule_pass_rate": next(
                    (
                        1.0 if m.passed else 0.0
                        for m in rule_score.metrics
                        if m.passed is not None
                    ),
                    None,
                ),
                "judge_overall": judge_record.overall if judge_record else None,
                "judge_rationale": judge_record.rationale if judge_record else None,
            }
        )
        progress.progress((i + 1) / len(candidate_records))

    (run_dir / "rule_scores.jsonl").write_text("\n".join(rule_lines) + "\n", encoding="utf-8")
    if judge_lines:
        (run_dir / "judge_scores.jsonl").write_text(
            "\n".join(judge_lines) + "\n", encoding="utf-8"
        )

    summary = summarize_run(run_dir, dataset_path)
    (run_dir / "summary.json").write_text(summary.model_dump_json(indent=2), encoding="utf-8")

    st.session_state["run_dir"] = str(run_dir)
    st.session_state["summary"] = summary.model_dump()
    st.session_state["rows"] = rows

if "rows" in st.session_state:
    st.subheader(f"Run: {st.session_state['run_dir']}")
    st.dataframe(pd.DataFrame(st.session_state["rows"]), use_container_width=True)

    summary = st.session_state["summary"]
    col1, col2, col3 = st.columns(3)
    col1.metric(
        "Mean rule pass rate",
        "-"
        if summary["mean_rule_pass_rate"] is None
        else f"{summary['mean_rule_pass_rate'] * 100:.1f}%",
    )
    col2.metric(
        "Mean judge overall",
        "-"
        if summary["mean_judge_overall"] is None
        else f"{summary['mean_judge_overall'] * 100:.1f}%",
    )
    col3.metric(
        "p95 latency (ms)",
        "-" if summary["p95_latency_ms"] is None else f"{summary['p95_latency_ms']:.1f}",
    )

    st.subheader("Compare to baseline")
    if DEFAULT_BASELINE_PATH.exists():
        baseline = Baseline.model_validate_json(
            DEFAULT_BASELINE_PATH.read_text(encoding="utf-8")
        )
        chart_df = pd.DataFrame(
            {
                "current": [
                    summary["mean_rule_pass_rate"] or 0.0,
                    summary["mean_judge_overall"] or 0.0,
                ],
                "baseline": [
                    baseline.summary.mean_rule_pass_rate or 0.0,
                    baseline.summary.mean_judge_overall or 0.0,
                ],
            },
            index=["rule_pass_rate", "judge_overall"],
        )
        st.bar_chart(chart_df)
    else:
        st.info(f"No baseline yet at {DEFAULT_BASELINE_PATH} -- accept a run to create one.")

    st.subheader("Write local baseline")
    st.caption(
        "Local only -- CI refuses --accept. Requires an explicit confirmation below, or "
        "open this page with ?confirm=1 in the URL."
    )
    confirmed = st.query_params.get("confirm") == "1" or st.checkbox(
        "I confirm I want to overwrite the local baseline with this run"
    )
    if st.button("Write local baseline", disabled=not confirmed):
        baseline = build_baseline(Path(st.session_state["run_dir"]))
        path = write_baseline(baseline)
        st.success(f"Wrote {path}")
