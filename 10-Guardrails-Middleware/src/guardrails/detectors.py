"""Rules-based prompt-injection detection.

Pattern-matches known injection *shapes* (instruction override, fake role
markers, exfiltration requests, restriction-bypass phrasing). This is a
defensive filter, not a catalogue of working attacks.

Phase 1 code: not adapted to the `Detector` protocol in `pipeline.py`, and
not imported by anything except `tests/test_detectors.py` -- dead from the
running app's perspective, kept intentionally. Do not "fix" this by wiring
it into `Guard`; that's a behavior change (see docs/PHASES.md for the
history). `rules.py`'s blocklists (`config/blocklists/injection.txt`,
`role_play.txt`) are the maintained equivalent that actually ships. Next:
`rules.py`.
"""

from __future__ import annotations

import re

from guardrails.types import Finding, Severity

_PATTERNS: list[tuple[str, Severity, re.Pattern[str]]] = [
    (
        "override_instructions",
        "high",
        re.compile(
            r"ignore (?:all |any )?(?:previous|prior|the above) instructions"
            r"|disregard (?:the )?(?:above|previous instructions)"
            r"|forget (?:your |all )?(?:previous )?instructions"
            r"|new instructions\s*:",
            re.IGNORECASE,
        ),
    ),
    (
        "role_confusion",
        "high",
        re.compile(
            r"^\s*(?:system|assistant)\s*:|<\|(?:system|assistant)\|>|^\s*###\s*instruction",
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
    (
        "exfiltration_request",
        "medium",
        re.compile(
            r"(?:reveal|print|show|repeat) your (?:system prompt|instructions|rules)"
            r"|what (?:is|was) your system prompt",
            re.IGNORECASE,
        ),
    ),
    (
        "restriction_bypass",
        "medium",
        re.compile(
            r"you have no (?:restrictions|rules|limits)"
            r"|no (?:restrictions|rules) apply"
            r"|developer mode"
            r"|act as if you have no (?:filter|restrictions|rules)",
            re.IGNORECASE,
        ),
    ),
    (
        "encoded_payload",
        "low",
        re.compile(r"[A-Za-z0-9+/]{80,}={0,2}"),
    ),
]

_WEIGHT: dict[Severity, int] = {"low": 1, "medium": 3, "high": 6}

HIGH_RISK_THRESHOLD = 6
MEDIUM_RISK_THRESHOLD = 3


def detect(text: str) -> list[Finding]:
    """Find injection-shaped patterns in `text`. Does not mutate `text`."""
    findings = [
        Finding(
            detector="injection",
            category=category,
            severity=severity,
            span=m.span(),
            matched_text=m.group()[:120],
        )
        for category, severity, pattern in _PATTERNS
        for m in pattern.finditer(text)
    ]
    findings.sort(key=lambda f: f.span[0])
    return findings


def risk_score(findings: list[Finding]) -> int:
    """Aggregate severity weight across injection findings."""
    return sum(_WEIGHT[f.severity] for f in findings if f.detector == "injection")
