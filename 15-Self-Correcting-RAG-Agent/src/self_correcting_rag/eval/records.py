"""Eval case + per-case result records."""

from dataclasses import dataclass
from typing import Literal

Category = Literal["in_corpus", "out_of_corpus", "needs_rewrite"]


@dataclass
class EvalCase:
    id: str
    question: str
    category: Category
    expected_source: str | None = None


@dataclass
class EvalCaseResult:
    case: EvalCase
    answered: bool
    illegal_citation_found: bool
    web_fired: bool
    reason: str | None
