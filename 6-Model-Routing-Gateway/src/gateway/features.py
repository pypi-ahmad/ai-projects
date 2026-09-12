"""Deterministic, offline complexity scoring — no network or LLM calls.
Turns a GatewayRequest into a Features record that route/router.py uses to
pick a tier. All weights/thresholds are external (config/features.yaml) so
scoring can be tuned without a code change.
Next: route/router.py (consumes Features.complexity_score/complexity_label).
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Any, Literal

import tiktoken

from .models import GatewayRequest

ComplexityLabel = Literal["simple", "medium", "hard"]

_enc = tiktoken.get_encoding("cl100k_base")


@dataclass
class Features:
    n_chars: int
    n_tokens_approx: int
    n_sentences: int
    has_code_fence: bool
    has_json_hint: bool
    has_question: bool
    keyword_hits: list[str]
    complexity_score: float   # 0.0 – 1.0
    complexity_label: ComplexityLabel


_JSON_HINT_RE = re.compile(
    r"\bjson\b|\bformat as\b|\boutput as\b|\breturn a\b", re.IGNORECASE
)
_QUESTION_START_RE = re.compile(
    r"^(what|how|why|when|who|where|which|is|are|can|could|should|would)\b",
    re.IGNORECASE,
)


class FeatureExtractor:
    """Deterministic feature extraction from a GatewayRequest.

    All weights and thresholds come from config/features.yaml so they are
    tunable without touching Python.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self._cfg = config

    def extract(self, request: GatewayRequest) -> Features:
        text = request.user_text

        # ── basic counts ────────────────────────────────────────────────────
        n_chars = len(text)
        n_tokens_approx = len(_enc.encode(text))
        parts = re.split(r"[.!?]+", text.strip())
        n_sentences = max(1, len([p for p in parts if p.strip()]))

        # ── pattern flags ───────────────────────────────────────────────────
        has_code_fence = "```" in text
        has_json_hint = bool(_JSON_HINT_RE.search(text))
        # has_question is reported on Features but does not feed into
        # complexity_score below — informational only, for callers/UI display.
        has_question = "?" in text or bool(_QUESTION_START_RE.match(text.strip()))

        # ── keyword hits (one hit per group) ────────────────────────────────
        keyword_hits: list[str] = []
        keyword_score = 0.0
        text_lower = text.lower()
        for group_name, group in self._cfg.get("keywords", {}).items():
            for term in group.get("terms", []):
                if term.lower() in text_lower:
                    keyword_hits.append(group_name)
                    keyword_score += group.get("weight", 0.0)
                    break  # one hit per group only

        keyword_score = min(1.0, keyword_score)

        # ── token length score (from bucket table) ───────────────────────────
        token_score = 0.0
        for bucket in self._cfg.get("token_weights", []):
            max_t = bucket.get("max")
            if max_t is None or n_tokens_approx <= max_t:
                token_score = bucket.get("score", 0.0)
                break

        # ── sentence normalisation ───────────────────────────────────────────
        sentence_norm = min(1.0, n_sentences / 20)

        # ── weighted sum → complexity_score ─────────────────────────────────
        fw = self._cfg.get("feature_weights", {})
        score = (
            keyword_score            * fw.get("keyword_hits",   0.35)
            + token_score            * fw.get("token_length",   0.30)
            + float(has_code_fence)  * fw.get("has_code_fence", 0.10)
            + float(has_json_hint)   * fw.get("has_json_hint",  0.10)
            + float(request.need_json) * fw.get("need_json",    0.10)
            + sentence_norm          * fw.get("n_sentences",    0.05)
        )
        score = round(min(1.0, max(0.0, score)), 4)

        # ── complexity label from thresholds ─────────────────────────────────
        thr = self._cfg.get("thresholds", {})
        if score < thr.get("simple", 0.35):
            label: ComplexityLabel = "simple"
        elif score < thr.get("medium", 0.65):
            label = "medium"
        else:
            label = "hard"

        return Features(
            n_chars=n_chars,
            n_tokens_approx=n_tokens_approx,
            n_sentences=n_sentences,
            has_code_fence=has_code_fence,
            has_json_hint=has_json_hint,
            has_question=has_question,
            keyword_hits=keyword_hits,
            complexity_score=score,
            complexity_label=label,
        )
