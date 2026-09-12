"""Checks a RunSummary against a GateConfig (and, if present, a Baseline)."""

from src.eval.models import RunSummary
from src.gate.models import Baseline, GateConfig, GateFailure


def evaluate_gate(
    summary: RunSummary, baseline: Baseline | None, config: GateConfig
) -> list[GateFailure]:
    failures: list[GateFailure] = []
    judge_missing = summary.mean_judge_overall is None
    # Gates both `min_judge_overall` and the judge half of `max_regression_delta`
    # below -- when true, a run with no judge data is not penalized for it.
    judge_bypassed = judge_missing and config.allow_missing_judge

    if config.min_rule_pass_rate is not None:
        if summary.mean_rule_pass_rate is None:
            failures.append(
                GateFailure(check="min_rule_pass_rate", message="no rule pass rate available")
            )
        elif summary.mean_rule_pass_rate < config.min_rule_pass_rate:
            failures.append(
                GateFailure(
                    check="min_rule_pass_rate",
                    message=(
                        f"{summary.mean_rule_pass_rate:.3f} < "
                        f"min_rule_pass_rate {config.min_rule_pass_rate:.3f}"
                    ),
                )
            )

    if config.min_judge_overall is not None:
        if judge_missing:
            if not config.allow_missing_judge:
                failures.append(
                    GateFailure(
                        check="min_judge_overall",
                        message="judge data missing and allow_missing_judge is false",
                    )
                )
        elif summary.mean_judge_overall < config.min_judge_overall:
            failures.append(
                GateFailure(
                    check="min_judge_overall",
                    message=(
                        f"{summary.mean_judge_overall:.3f} < "
                        f"min_judge_overall {config.min_judge_overall:.3f}"
                    ),
                )
            )

    if (
        config.max_p95_latency_ms is not None
        and summary.p95_latency_ms is not None
        and summary.p95_latency_ms > config.max_p95_latency_ms
    ):
        failures.append(
            GateFailure(
                check="max_p95_latency_ms",
                message=(
                    f"{summary.p95_latency_ms:.1f} > "
                    f"max_p95_latency_ms {config.max_p95_latency_ms:.1f}"
                ),
            )
        )

    if config.max_regression_delta is not None and baseline is not None:
        delta = config.max_regression_delta

        base_rule = baseline.summary.mean_rule_pass_rate
        if summary.mean_rule_pass_rate is not None and base_rule is not None:
            threshold = base_rule - delta
            if summary.mean_rule_pass_rate < threshold:
                failures.append(
                    GateFailure(
                        check="max_regression_delta.rule_pass_rate",
                        message=(
                            f"{summary.mean_rule_pass_rate:.3f} < baseline {base_rule:.3f} "
                            f"- delta {delta:.3f}"
                        ),
                    )
                )

        base_judge = baseline.summary.mean_judge_overall
        if judge_missing:
            if not judge_bypassed and base_judge is not None:
                failures.append(
                    GateFailure(
                        check="max_regression_delta.judge_overall",
                        message="judge data missing and allow_missing_judge is false",
                    )
                )
        elif base_judge is not None:
            threshold = base_judge - delta
            if summary.mean_judge_overall < threshold:
                failures.append(
                    GateFailure(
                        check="max_regression_delta.judge_overall",
                        message=(
                            f"{summary.mean_judge_overall:.3f} < baseline {base_judge:.3f} "
                            f"- delta {delta:.3f}"
                        ),
                    )
                )

    return failures
