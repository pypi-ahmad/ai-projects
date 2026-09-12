"""Deterministic (rule-based) metrics. Pure functions -- given the text(s)
they need, each returns one MetricResult. See docs/METRICS.md for the exact
definition and normalization convention of each one.
"""

import json
import re

from src.metrics.models import MetricResult

_WHITESPACE_RE = re.compile(r"\s+")


def _normalize(text: str, *, case_sensitive: bool) -> str:
    normalized = _WHITESPACE_RE.sub(" ", text).strip()
    return normalized if case_sensitive else normalized.lower()


def exact_match(candidate: str, expected: str, *, case_sensitive: bool = False) -> MetricResult:
    passed = _normalize(candidate, case_sensitive=case_sensitive) == _normalize(
        expected, case_sensitive=case_sensitive
    )
    return MetricResult(
        name="exact_match",
        score=1.0 if passed else 0.0,
        passed=passed,
        detail=None if passed else f"expected {expected!r}",
    )


def contains_all(
    candidate: str, phrases: list[str], *, case_sensitive: bool = False
) -> MetricResult:
    haystack = candidate if case_sensitive else candidate.lower()
    missing = [p for p in phrases if (p if case_sensitive else p.lower()) not in haystack]
    passed = not missing
    return MetricResult(
        name="contains_all",
        score=1.0 if passed else 0.0,
        passed=passed,
        detail=None if passed else f"missing: {missing}",
    )


def contains_any(
    candidate: str, phrases: list[str], *, case_sensitive: bool = False
) -> MetricResult:
    haystack = candidate if case_sensitive else candidate.lower()
    passed = any((p if case_sensitive else p.lower()) in haystack for p in phrases)
    return MetricResult(
        name="contains_any",
        score=1.0 if passed else 0.0,
        passed=passed,
        detail=None if passed else f"none of {phrases} found",
    )


def forbidden_any(
    candidate: str, phrases: list[str], *, case_sensitive: bool = False
) -> MetricResult:
    haystack = candidate if case_sensitive else candidate.lower()
    hits = [p for p in phrases if (p if case_sensitive else p.lower()) in haystack]
    passed = not hits
    return MetricResult(
        name="forbidden_any",
        score=1.0 if passed else 0.0,
        passed=passed,
        detail=None if passed else f"found forbidden: {hits}",
    )


def regex_match(candidate: str, pattern: str) -> MetricResult:
    match = re.search(pattern, candidate)
    passed = match is not None
    return MetricResult(
        name="regex",
        score=1.0 if passed else 0.0,
        passed=passed,
        detail=None if passed else f"no match for {pattern!r}",
    )


def json_parse_ok(candidate: str) -> MetricResult:
    try:
        json.loads(candidate)
    except json.JSONDecodeError as exc:
        return MetricResult(name="json_parse_ok", score=0.0, passed=False, detail=str(exc))
    return MetricResult(name="json_parse_ok", score=1.0, passed=True, detail=None)


def length_tokens_approx(candidate: str) -> MetricResult:
    # Word-count proxy for token count -- informational, no pass/fail threshold.
    count = len(candidate.split())
    return MetricResult(
        name="length_tokens_approx", score=None, passed=None, detail=f"~{count} tokens"
    )


def latency_ms_passthrough(latency_ms: float) -> MetricResult:
    return MetricResult(name="latency_ms", score=None, passed=None, detail=f"{latency_ms:.1f}")
