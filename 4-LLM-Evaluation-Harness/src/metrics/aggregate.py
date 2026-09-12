"""Decides which rule metrics apply to a case, based on what's truthy on
case.expected, and builds the resulting CaseScore. A field that is None or
empty means its metric is skipped entirely -- it never appears in
CaseScore.metrics as a failed/null result.
"""

from src.dataset import Case
from src.metrics.models import CaseScore, MetricResult
from src.metrics.rules import (
    contains_all,
    contains_any,
    exact_match,
    forbidden_any,
    json_parse_ok,
    latency_ms_passthrough,
    length_tokens_approx,
    regex_match,
)


def score_case(case: Case, *, text: str | None, latency_ms: float) -> CaseScore:
    metrics: list[MetricResult] = [latency_ms_passthrough(latency_ms)]

    if text is None:
        return CaseScore(case_id=case.id, metrics=metrics)

    metrics.append(length_tokens_approx(text))

    expected = case.expected
    if expected.answer:
        metrics.append(exact_match(text, expected.answer))
    if expected.contains_all:
        metrics.append(contains_all(text, expected.contains_all))
    if expected.contains_any:
        metrics.append(contains_any(text, expected.contains_any))
    if expected.forbidden_any:
        metrics.append(forbidden_any(text, expected.forbidden_any))
    if expected.regex:
        metrics.append(regex_match(text, expected.regex))
    if expected.json_schema_name:
        metrics.append(json_parse_ok(text))

    return CaseScore(case_id=case.id, metrics=metrics)
