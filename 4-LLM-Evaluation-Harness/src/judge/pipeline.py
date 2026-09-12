"""Judge pipeline: render prompt -> call judge model -> parse+validate
JudgeVerdict -> one repair pass on failure -> judge_error if still invalid.
Every "ok" JudgeRecord is built exclusively from a validated JudgeVerdict --
judge free text never stands in as a score.
"""

from src.dataset import Case
from src.judge.models import JudgeRecord
from src.judge.parsing import parse_verdict
from src.judge.prompt import JUDGE_VERDICT_SCHEMA_HINT, render_judge_prompt
from src.judge.repair import repair_json
from src.judge.rubric import Rubric
from src.providers.base import Provider


def judge_case(
    case: Case,
    *,
    candidate_text: str,
    rubric: Rubric,
    judge_provider: Provider,
    judge_provider_name: str,
    judge_model: str,
    candidate_provider_name: str,
    candidate_model: str,
) -> JudgeRecord | None:
    judge = case.judge
    if judge is None:
        return None

    same_model_warning = (
        judge_provider_name == candidate_provider_name and judge_model == candidate_model
    )

    def error_record(message: str) -> JudgeRecord | None:
        if not judge.required:
            return None
        return JudgeRecord(
            case_id=case.id,
            rubric_id=rubric.id,
            judge_provider=judge_provider_name,
            judge_model=judge_model,
            same_model_warning=same_model_warning,
            status="judge_error",
            passed=False,
            error=message,
        )

    prompt = render_judge_prompt(rubric, case, candidate_text)

    try:
        raw = judge_provider.complete(system=None, user=prompt, model=judge_model, think=False)
    except Exception as exc:
        return error_record(f"judge call failed: {exc}")

    try:
        verdict = parse_verdict(raw)
    except ValueError as exc:
        repaired = repair_json(
            raw,
            schema_hint=JUDGE_VERDICT_SCHEMA_HINT,
            fallback_provider=judge_provider,
            fallback_model=judge_model,
        )
        if repaired is None:
            return error_record(f"malformed JSON, repair unavailable: {exc}")
        try:
            verdict = parse_verdict(repaired)
        except ValueError as exc2:
            return error_record(f"malformed JSON even after repair: {exc2}")

    return JudgeRecord(
        case_id=case.id,
        rubric_id=rubric.id,
        judge_provider=judge_provider_name,
        judge_model=judge_model,
        same_model_warning=same_model_warning,
        status="ok",
        scores=verdict.scores,
        overall=verdict.overall,
        passed=verdict.passed,
        rationale=verdict.rationale,
        evidence_spans=verdict.evidence_spans,
    )
