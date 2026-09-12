from src.eval.models import RunSummary
from src.gate.evaluate import evaluate_gate
from src.gate.models import Baseline, BaselineConfig, GateConfig


def _summary(**overrides) -> RunSummary:
    data = {
        "run_id": "r1",
        "dataset_path": "datasets/golden/smoke.jsonl",
        "dataset_hash": "hash",
        "n_cases": 5,
        "n_error": 0,
        "mean_rule_pass_rate": 0.8,
        "mean_judge_overall": 0.9,
        "p95_latency_ms": 1000.0,
    }
    data.update(overrides)
    return RunSummary.model_validate(data)


def _baseline(**overrides) -> Baseline:
    summary = _summary(**overrides.pop("summary_overrides", {}))
    config = BaselineConfig(dataset_path=summary.dataset_path, dataset_hash=summary.dataset_hash)
    return Baseline(summary=summary, config=config)


def test_passes_when_no_thresholds_configured():
    failures = evaluate_gate(_summary(), None, GateConfig())
    assert failures == []


def test_fails_min_rule_pass_rate():
    failures = evaluate_gate(
        _summary(mean_rule_pass_rate=0.5), None, GateConfig(min_rule_pass_rate=0.75)
    )
    assert any(f.check == "min_rule_pass_rate" for f in failures)


def test_passes_min_rule_pass_rate_at_threshold():
    failures = evaluate_gate(
        _summary(mean_rule_pass_rate=0.75), None, GateConfig(min_rule_pass_rate=0.75)
    )
    assert failures == []


def test_fails_min_judge_overall():
    failures = evaluate_gate(
        _summary(mean_judge_overall=0.5), None, GateConfig(min_judge_overall=0.7)
    )
    assert any(f.check == "min_judge_overall" for f in failures)


def test_fails_max_p95_latency():
    failures = evaluate_gate(
        _summary(p95_latency_ms=5000.0), None, GateConfig(max_p95_latency_ms=2000.0)
    )
    assert any(f.check == "max_p95_latency_ms" for f in failures)


def test_missing_judge_fails_when_not_allowed():
    failures = evaluate_gate(
        _summary(mean_judge_overall=None),
        None,
        GateConfig(min_judge_overall=0.7, allow_missing_judge=False),
    )
    assert any(f.check == "min_judge_overall" for f in failures)


def test_missing_judge_bypassed_when_allowed():
    failures = evaluate_gate(
        _summary(mean_judge_overall=None),
        None,
        GateConfig(min_judge_overall=0.7, allow_missing_judge=True),
    )
    assert failures == []


def test_no_baseline_skips_regression_checks_but_keeps_absolute_ones():
    failures = evaluate_gate(
        _summary(mean_rule_pass_rate=0.9),
        None,
        GateConfig(min_rule_pass_rate=0.5, max_regression_delta=0.05),
    )
    assert failures == []


def test_regression_delta_fails_when_current_drops_too_much():
    baseline = _baseline(summary_overrides={"mean_rule_pass_rate": 0.9})
    failures = evaluate_gate(
        _summary(mean_rule_pass_rate=0.8),
        baseline,
        GateConfig(max_regression_delta=0.05),
    )
    assert any(f.check == "max_regression_delta.rule_pass_rate" for f in failures)


def test_regression_delta_passes_within_tolerance():
    baseline = _baseline(summary_overrides={"mean_rule_pass_rate": 0.9})
    failures = evaluate_gate(
        _summary(mean_rule_pass_rate=0.87),
        baseline,
        GateConfig(max_regression_delta=0.05),
    )
    assert failures == []


def test_regression_delta_on_judge_bypassed_when_missing_and_allowed():
    baseline = _baseline(summary_overrides={"mean_judge_overall": 0.9})
    failures = evaluate_gate(
        _summary(mean_judge_overall=None),
        baseline,
        GateConfig(max_regression_delta=0.05, allow_missing_judge=True),
    )
    assert failures == []


def test_regression_delta_on_judge_fails_when_missing_and_not_allowed():
    baseline = _baseline(summary_overrides={"mean_judge_overall": 0.9})
    failures = evaluate_gate(
        _summary(mean_judge_overall=None),
        baseline,
        GateConfig(max_regression_delta=0.05, allow_missing_judge=False),
    )
    assert any(f.check == "max_regression_delta.judge_overall" for f in failures)
