"""Builds the judge prompt and the schema hint shared with the repair pass."""

from src.dataset import Case
from src.judge.rubric import Rubric

JUDGE_VERDICT_SCHEMA_HINT = (
    '{"scores": {"<dimension_name>": <float 0-1>, ...}, "overall": <float 0-1>, '
    '"pass": <true|false>, "rationale": "<short text>", "evidence_spans": ["<quote>", ...]}'
)


def render_judge_prompt(rubric: Rubric, case: Case, candidate_text: str) -> str:
    dimensions = "\n".join(
        f"- {d.name} (weight {d.weight}): {d.description}" for d in rubric.dimensions
    )
    parts = [
        f'You are grading an AI assistant\'s answer using the rubric "{rubric.id}" '
        f"(v{rubric.version}).",
        "Score each dimension from 0.0 to 1.0:",
        dimensions,
        "",
        f"User question:\n{case.input.user}",
    ]
    if case.input.context:
        parts.append(f"\nContext given to the assistant:\n{case.input.context}")
    if case.expected.answer:
        parts.append(
            "\nReference answer (for comparison; the assistant's answer need not match it "
            f"verbatim):\n{case.expected.answer}"
        )
    parts.append(f"\nAssistant's answer to grade:\n{candidate_text}")
    parts.append(
        "\nRespond with ONLY a single JSON object, no prose, no code fences, matching "
        f"exactly this shape:\n{JUDGE_VERDICT_SCHEMA_HINT}"
    )
    return "\n".join(parts)
