"""Rules-based PII detection and redaction (Phase 3).

Each `Span` carries a `replacement` placeholder, never the raw matched text —
so findings and redacted output are both safe to log (see docs/PII.md). The
same raw value always maps to the same placeholder within one `detect()`
call; 2+ distinct values of one type get numbered placeholders, so a
downstream model can still tell "the email mentioned twice" from "two
different emails" without ever seeing either one.

Next: `rules.py` for the other input/output filtering pass (blocklists,
length limits, encoding evasion) that runs alongside this one.
"""

from __future__ import annotations

import math
import os
import re
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from guardrails.models import Finding, GuardContext, Span, apply_spans, drop_overlapping_spans

if TYPE_CHECKING:
    from collections.abc import Callable

DEFAULT_PII_CONFIG: dict[str, bool] = {
    "email": True,
    "phone": True,
    "credit_card": True,
    "ip_address": True,
    "api_key": True,
    "aadhaar": False,  # possible-only, unvalidated shape match -- opt in, see docs/PII.md
    "pan": False,  # possible-only, unvalidated shape match -- opt in, see docs/PII.md
}

_CONFIG_ENV_VAR = "GUARDRAILS_PII_CONFIG"
_DEFAULT_CONFIG_PATH = Path("config/pii.yaml")

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# Generic-ish + Indian mobile formats. Both are shape heuristics with real
# false-positive risk: the generic pattern matches plenty of non-phone numeric
# sequences (order numbers, reference codes); the Indian pattern matches ANY
# 10-digit number starting 6-9, which includes non-phone IDs too. See
# docs/PII.md.
_PHONE_GENERIC = re.compile(r"(?<!\d)(?:\+?\d{1,3}[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}(?!\d)")
_PHONE_IN = re.compile(r"(?<!\d)(?:\+?91[ -]?)?[6-9]\d{9}(?!\d)")

_IPV4 = re.compile(
    r"(?<!\d)(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?!\d)"
)

_CREDIT_CARD_CANDIDATE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_CREDIT_CARD_MIN_DIGITS = 13
_CREDIT_CARD_MAX_DIGITS = 19
_LUHN_CARRY = 9

_AWS_ACCESS_KEY = re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")
_PREFIXED_SECRET = re.compile(
    r"\b(?:sk|pk|api[_-]?key|secret)[_-][A-Za-z0-9]{16,}\b", re.IGNORECASE
)
_TOKEN_CANDIDATE = re.compile(r"[A-Za-z0-9_-]{20,}")
_MIN_TOKEN_ENTROPY = 3.0  # bits/char -- cuts most prose/plain words, keeps random-looking tokens

# Shape only -- no checksum, no legal validation. Do not treat a match as a
# confirmed Aadhaar/PAN number. See docs/PII.md.
_AADHAAR = re.compile(r"(?<!\d)[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}(?!\d)")
_PAN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")


def load_pii_config(path: str | Path | None = None) -> dict[str, bool]:
    """Load per-type on/off flags, falling back to `DEFAULT_PII_CONFIG`.

    Resolves `path`, then `$GUARDRAILS_PII_CONFIG`, then `config/pii.yaml`
    relative to the current working directory. A missing file or missing
    keys fall back to the default for that key.

    Not called automatically by `detect()`/`redact()`/`PiiDetector` -- a
    caller must load this and pass the result as `config` explicitly.
    Neither `api.py` nor `ui.py` do this today; both run on
    `DEFAULT_PII_CONFIG`, so `config/pii.yaml` has no effect unless
    something wires this in.
    """
    config = dict(DEFAULT_PII_CONFIG)
    resolved = Path(path or os.getenv(_CONFIG_ENV_VAR) or _DEFAULT_CONFIG_PATH)
    if not resolved.exists():
        return config

    data: Any = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
    for key, value in data.items():
        if key in config:
            config[key] = bool(value)
    return config


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > _LUHN_CARRY:
                d -= _LUHN_CARRY
        total += d
    return total % 10 == 0


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    counts = Counter(s)
    length = len(s)
    return -sum((n / length) * math.log2(n / length) for n in counts.values())


def _looks_like_high_entropy_token(s: str) -> bool:
    has_letter = any(c.isalpha() for c in s)
    has_digit = any(c.isdigit() for c in s)
    return has_letter and has_digit and _shannon_entropy(s) >= _MIN_TOKEN_ENTROPY


def _span(match: re.Match[str], type_: str, score: float) -> Span:
    start, end = match.span()
    return Span(start=start, end=end, type=type_, score=score)


def _email_spans(text: str) -> list[Span]:
    return [_span(m, "email", 0.9) for m in _EMAIL.finditer(text)]


def _aadhaar_spans(text: str) -> list[Span]:
    return [_span(m, "aadhaar_possible", 0.5) for m in _AADHAAR.finditer(text)]


def _pan_spans(text: str) -> list[Span]:
    return [_span(m, "pan_possible", 0.6) for m in _PAN.finditer(text)]


def _phone_spans(text: str) -> list[Span]:
    return [_span(m, "phone", 0.6) for m in _PHONE_GENERIC.finditer(text)] + [
        _span(m, "phone", 0.6) for m in _PHONE_IN.finditer(text)
    ]


def _credit_card_spans(text: str) -> list[Span]:
    spans: list[Span] = []
    for m in _CREDIT_CARD_CANDIDATE.finditer(text):
        digits = re.sub(r"[ -]", "", m.group())
        length_ok = _CREDIT_CARD_MIN_DIGITS <= len(digits) <= _CREDIT_CARD_MAX_DIGITS
        if length_ok and _luhn_ok(digits):
            spans.append(_span(m, "credit_card", 1.0))
    return spans


def _ip_spans(text: str) -> list[Span]:
    return [_span(m, "ip_address", 0.7) for m in _IPV4.finditer(text)]


def _api_key_spans(text: str) -> list[Span]:
    spans = [_span(m, "api_key", 0.9) for m in _AWS_ACCESS_KEY.finditer(text)]
    spans += [_span(m, "api_key", 0.85) for m in _PREFIXED_SECRET.finditer(text)]
    spans += [
        _span(m, "api_key", 0.6)
        for m in _TOKEN_CANDIDATE.finditer(text)
        if _looks_like_high_entropy_token(m.group())
    ]
    return spans


# Order matters: earlier entries win ties in `_drop_overlaps` (e.g. aadhaar
# before phone, since a bare digit run can satisfy both).
_DETECTORS: list[tuple[str, Callable[[str], list[Span]]]] = [
    ("email", _email_spans),
    ("aadhaar", _aadhaar_spans),
    ("pan", _pan_spans),
    ("phone", _phone_spans),
    ("credit_card", _credit_card_spans),
    ("ip_address", _ip_spans),
    ("api_key", _api_key_spans),
]


def _detect_spans(text: str, config: dict[str, bool]) -> list[Span]:
    spans: list[Span] = []
    for key, collect in _DETECTORS:
        if config.get(key, DEFAULT_PII_CONFIG.get(key, False)):
            spans += collect(text)
    return drop_overlapping_spans(spans)


def _assign_stable_replacements(spans: list[Span], text: str) -> None:
    """Mutate every span's `replacement` in place.

    Same raw value -> same tag. 2+ distinct values of one type get a numeric
    suffix, in first-seen order.
    """
    seen: dict[str, list[str]] = {}
    for span in spans:
        raw = text[span.start : span.end]
        seen.setdefault(span.type, [])
        if raw not in seen[span.type]:
            seen[span.type].append(raw)

    tag_for: dict[tuple[str, str], str] = {}
    for type_, values in seen.items():
        base = type_.upper()
        if len(values) == 1:
            tag_for[(type_, values[0])] = f"[{base}]"
        else:
            for i, raw in enumerate(values, start=1):
                tag_for[(type_, raw)] = f"[{base}_{i}]"

    for span in spans:
        span.replacement = tag_for[(span.type, text[span.start : span.end])]


def detect(text: str, config: dict[str, bool] | None = None) -> Finding:
    """Find PII in `text` per `config` (defaults to `DEFAULT_PII_CONFIG`).

    Returns one `Finding` carrying every matched `Span`, each with a stable
    `replacement` placeholder already assigned. Always returns a `Finding`,
    even with no matches (`severity="info"`, empty `spans`).
    """
    cfg = config or DEFAULT_PII_CONFIG
    spans = _detect_spans(text, cfg)
    _assign_stable_replacements(spans, text)
    return Finding(
        detector_id="pii",
        severity="warn" if spans else "info",
        spans=spans,
        message=f"{len(spans)} PII span(s)" if spans else "no PII found",
    )


def redact(text: str, finding: Finding | None = None, config: dict[str, bool] | None = None) -> str:
    """Return `text` with every PII span's `replacement` applied."""
    finding = detect(text, config) if finding is None else finding
    return apply_spans(text, finding.spans)


class PiiDetector:
    """`Detector`-conforming wrapper around `detect()` (see `guardrails.pipeline.Detector`).

    Never blocks: PII findings are always `severity="warn"` (transform), matching the
    "standard" policy documented in `docs/POLICIES.md`.
    """

    detector_id = "pii"

    def __init__(self, config: dict[str, bool] | None = None) -> None:
        self.config = config

    def run(self, text: str, context: GuardContext) -> Finding:  # noqa: ARG002 - protocol shape
        return detect(text, self.config)
