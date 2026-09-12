"""Loads eval cases from a JSONL fixture and runs each through the agent loop
(via run_safe -- one bad model response must not abort the whole eval run).
"""

import json
from pathlib import Path

from self_correcting_rag.agent.loop import run_safe
from self_correcting_rag.agent.schemas import LoopPolicy
from self_correcting_rag.eval.records import EvalCase, EvalCaseResult
from self_correcting_rag.llm.base import Provider


def load_cases(path: Path) -> list[EvalCase]:
    cases = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            cases.append(EvalCase(**json.loads(line)))
    return cases


def run_eval(
    cases: list[EvalCase], *, index_dir: Path, provider: Provider, policy: LoopPolicy
) -> list[EvalCaseResult]:
    results = []
    for case in cases:
        result = run_safe(case.question, index_dir=index_dir, provider=provider, policy=policy)
        # Reads AgentTrace step details by stage name + dict key, matching what
        # agent/loop.py's run() actually records (not a separate/typed contract) -- if
        # loop.py's trace.record() calls change their keys, this silently stops detecting
        # illegal citations / web firing instead of raising.
        illegal_found = any(
            step.stage == "generate" and step.detail.get("illegal_citation_found")
            for step in result.trace.steps
        )
        web_fired = any(
            step.stage == "web" and step.detail.get("urls") for step in result.trace.steps
        )
        results.append(
            EvalCaseResult(
                case=case,
                answered=result.answer is not None,
                illegal_citation_found=illegal_found,
                web_fired=web_fired,
                reason=result.reason,
            )
        )
    return results
