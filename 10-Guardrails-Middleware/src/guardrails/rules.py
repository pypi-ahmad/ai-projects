"""Rules-only input/output filtering: length, blocklists, control chars, encoding
evasion, leak phrases, denied topics (Phase 4). No LLM anywhere in this module.

Severity per category comes from `config/rules.yaml` (falls back to
`DEFAULT_RULES_CONFIG`). The "standard" policy (docs/POLICIES.md) is expressed
entirely through that config's defaults: input categories default to `block`,
output categories default to `warn` (transform, never block) -- this module
doesn't hardcode that split, it just ships defaults that match it.

Next: `providers.py` for the optional LLM classifier lane that runs after
these rules on input.
"""

from __future__ import annotations

import copy
import os
import re
import unicodedata
from pathlib import Path
from typing import Any

import yaml

from guardrails.models import Finding, GuardContext, Severity, Span, drop_overlapping_spans

DEFAULT_RULES_CONFIG: dict[str, Any] = {
    "input": {
        "max_chars": {"enabled": True, "limit": 8000, "severity": "block"},
        "blocklist": {"enabled": True, "severity": "block"},
        "control_char": {"enabled": True, "severity": "block"},
        "encoding_evasion": {"enabled": True, "severity": "block"},
    },
    "output": {
        "leak_pattern": {"enabled": True, "severity": "warn"},
        "denied_topics": {"enabled": True, "severity": "warn"},
    },
}

_CONFIG_ENV_VAR = "GUARDRAILS_RULES_CONFIG"
_DEFAULT_CONFIG_PATH = Path("config/rules.yaml")

_BLOCKLIST_DIR = Path("config/blocklists")
_INPUT_BLOCKLIST_FILES = ["injection.txt", "role_play.txt"]
_OUTPUT_LEAK_FILES = ["leak_phrases.txt"]
_OUTPUT_DENIED_TOPICS_FILES = ["denied_topics.txt"]

_CONTROL_CHAR = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# A handful of common Cyrillic/Greek letters that look like Latin ones.
# Not exhaustive -- see docs/DETECTORS.md for limits.
_HOMOGLYPH_MAP = str.maketrans(
    {
        "а": "a",
        "е": "e",
        "о": "o",
        "р": "p",
        "с": "c",
        "х": "x",
        "у": "y",
        "Α": "A",
        "Β": "B",
        "Ε": "E",
        "Ζ": "Z",
        "Η": "H",
        "Ι": "I",
        "Κ": "K",
        "Μ": "M",
        "Ν": "N",
        "Ο": "O",
        "Ρ": "P",
        "Τ": "T",
        "Υ": "Y",
        "Χ": "X",
    }
)

_SEVERITY_RANK: dict[Severity, int] = {"info": 0, "warn": 1, "block": 2}


def load_rules_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load per-category enabled/severity settings, falling back to `DEFAULT_RULES_CONFIG`.

    Resolves `path`, then `$GUARDRAILS_RULES_CONFIG`, then `config/rules.yaml`
    relative to the current working directory. A missing file, or a missing
    category/key within it, falls back to the default for that key.

    Not called automatically by `detect_input()`/`detect_output()` or
    `InputRulesDetector`/`OutputRulesDetector` -- a caller must load this and
    pass the result as `config` explicitly.
    """
    config = copy.deepcopy(DEFAULT_RULES_CONFIG)
    resolved = Path(path or os.getenv(_CONFIG_ENV_VAR) or _DEFAULT_CONFIG_PATH)
    if not resolved.exists():
        return config

    data: Any = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
    for direction in ("input", "output"):
        for category, overrides in (data.get(direction) or {}).items():
            if category in config[direction] and isinstance(overrides, dict):
                config[direction][category].update(overrides)
    return config


def _normalize(text: str) -> str:
    """NFKC-normalize (folds fullwidth/compatibility forms to ASCII) plus a small
    homoglyph swap. Not exhaustive -- see docs/DETECTORS.md.
    """
    return unicodedata.normalize("NFKC", text).translate(_HOMOGLYPH_MAP)


def _aggregate_severity(severities: list[Severity]) -> Severity:
    if not severities:
        return "info"
    return max(severities, key=lambda s: _SEVERITY_RANK[s])


def _parse_blocklist_file(path: Path) -> list[tuple[str, re.Pattern[str]]]:
    category = path.stem
    entries: list[tuple[str, re.Pattern[str]]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("regex:"):
            entries.append((category, re.compile(line[len("regex:") :].strip(), re.IGNORECASE)))
        else:
            entries.append((category, re.compile(re.escape(line), re.IGNORECASE)))
    return entries


def _load_blocklists(filenames: list[str]) -> list[tuple[str, re.Pattern[str]]]:
    entries: list[tuple[str, re.Pattern[str]]] = []
    for name in filenames:
        path = _BLOCKLIST_DIR / name
        if path.exists():
            entries += _parse_blocklist_file(path)
    return entries


def _match_entries(text: str, entries: list[tuple[str, re.Pattern[str]]]) -> list[Span]:
    return [
        Span(start=m.start(), end=m.end(), type=f"blocklist_{category}", score=0.9)
        for category, pattern in entries
        for m in pattern.finditer(text)
    ]


def detect_input(text: str, config: dict[str, Any] | None = None) -> Finding:
    """Run every enabled input rule over `text`, return one aggregate `Finding`."""
    cfg = config or DEFAULT_RULES_CONFIG
    icfg = cfg["input"]
    spans: list[Span] = []
    fired: list[Severity] = []

    max_chars_cfg = icfg["max_chars"]
    if max_chars_cfg["enabled"] and len(text) > max_chars_cfg["limit"]:
        spans.append(
            Span(start=max_chars_cfg["limit"], end=len(text), type="max_chars_exceeded", score=1.0)
        )
        fired.append(max_chars_cfg["severity"])

    cc_cfg = icfg["control_char"]
    if cc_cfg["enabled"]:
        cc_spans = [
            Span(start=m.start(), end=m.end(), type="control_char", score=1.0)
            for m in _CONTROL_CHAR.finditer(text)
        ]
        if cc_spans:
            spans += cc_spans
            fired.append(cc_cfg["severity"])

    bl_cfg = icfg["blocklist"]
    if bl_cfg["enabled"]:
        entries = _load_blocklists(_INPUT_BLOCKLIST_FILES)
        bl_spans = _match_entries(text, entries)
        if bl_spans:
            spans += bl_spans
            fired.append(bl_cfg["severity"])

        ee_cfg = icfg["encoding_evasion"]
        if ee_cfg["enabled"]:
            normalized = _normalize(text)
            if normalized != text:
                raw_ranges = {(s.start, s.end) for s in bl_spans}
                normalized_spans = _match_entries(normalized, entries)
                new_hits = [s for s in normalized_spans if (s.start, s.end) not in raw_ranges]
                if new_hits:
                    for s in new_hits:
                        s.type = "encoding_evasion"
                    spans += new_hits
                    fired.append(ee_cfg["severity"])

    spans = drop_overlapping_spans(spans)
    overall = _aggregate_severity(fired)
    return Finding(
        detector_id="input_rules",
        severity=overall,
        spans=spans,
        message=f"{len(spans)} rule match(es)" if spans else "no rule matches",
    )


def detect_output(text: str, config: dict[str, Any] | None = None) -> Finding:
    """Run every enabled output rule over `text`, return one aggregate `Finding`.

    PII on output is a separate pass (`guardrails.pii.detect`/`PiiDetector`) --
    not duplicated here. See docs/PII.md.
    """
    cfg = config or DEFAULT_RULES_CONFIG
    ocfg = cfg["output"]
    spans: list[Span] = []
    fired: list[Severity] = []

    leak_cfg = ocfg["leak_pattern"]
    if leak_cfg["enabled"]:
        leak_spans = _match_entries(text, _load_blocklists(_OUTPUT_LEAK_FILES))
        if leak_spans:
            spans += leak_spans
            fired.append(leak_cfg["severity"])

    dt_cfg = ocfg["denied_topics"]
    if dt_cfg["enabled"]:
        dt_spans = _match_entries(text, _load_blocklists(_OUTPUT_DENIED_TOPICS_FILES))
        if dt_spans:
            spans += dt_spans
            fired.append(dt_cfg["severity"])

    spans = drop_overlapping_spans(spans)
    overall = _aggregate_severity(fired)
    return Finding(
        detector_id="output_rules",
        severity=overall,
        spans=spans,
        message=f"{len(spans)} rule match(es)" if spans else "no rule matches",
    )


class InputRulesDetector:
    """`Detector`-conforming wrapper around `detect_input()`."""

    detector_id = "input_rules"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config

    def run(self, text: str, context: GuardContext) -> Finding:  # noqa: ARG002 - protocol shape
        return detect_input(text, self.config)


class OutputRulesDetector:
    """`Detector`-conforming wrapper around `detect_output()`."""

    detector_id = "output_rules"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config

    def run(self, text: str, context: GuardContext) -> Finding:  # noqa: ARG002 - protocol shape
        return detect_output(text, self.config)
