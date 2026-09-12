"""Critique: score retrieval sufficiency as JSON, then enforce the decision
rules in code -- the model's `decision` is a recommendation, not the source
of truth. See docs/LOOP.md for the decision table this implements.
"""

from self_correcting_rag.agent.context import format_context_blocks
from self_correcting_rag.agent.json_llm import call_json
from self_correcting_rag.agent.prompts import CRITIQUE_SYSTEM_PROMPT
from self_correcting_rag.agent.schemas import CritiqueResult, LoopPolicy
from self_correcting_rag.llm.base import Provider
from self_correcting_rag.retrieve.records import RetrievalResult

DEFAULT_CRITIQUE_MODEL = "qwen3.5:0.8b"


def enforce_decision(
    critique_result: CritiqueResult, *, policy: LoopPolicy, iteration: int, chunks_present: bool
) -> tuple[str, str | None]:
    """Returns (legal_decision, override_reason). override_reason is None if
    the model's own decision already satisfied every postcondition:

    - answer only if grounded >= threshold AND at least one chunk was retrieved
    - web only if the corpus looks insufficient AND policy.web_enabled
    - abstain if insufficient AND web is off (and no retries remain)
    - otherwise retry, while iterations remain
    """
    grounded_ok = critique_result.grounded >= policy.confidence_threshold and chunks_present
    retries_left = iteration < policy.max_iters

    if grounded_ok:
        legal = "answer"
    elif retries_left:
        legal = "retry"
    elif policy.web_enabled:
        legal = "web"
    else:
        legal = "abstain"

    if critique_result.decision == legal:
        return legal, None
    return legal, (
        f"overrode model's decision '{critique_result.decision}' -> '{legal}' "
        f"(grounded={critique_result.grounded:.2f}, threshold={policy.confidence_threshold}, "
        f"chunks_present={chunks_present}, retries_left={retries_left}, "
        f"web_enabled={policy.web_enabled})"
    )


def critique(
    provider: Provider,
    model: str,
    *,
    query: str,
    chunks: list[RetrievalResult],
    policy: LoopPolicy,
    iteration: int = 1,
) -> CritiqueResult:
    user = f"Query: {query}\n\nRetrieved context:\n{format_context_blocks(chunks)}"
    result = call_json(
        provider, system=CRITIQUE_SYSTEM_PROMPT, user=user, model=model, schema=CritiqueResult
    )

    decision, override_reason = enforce_decision(
        result, policy=policy, iteration=iteration, chunks_present=bool(chunks)
    )
    if override_reason is not None:
        result = result.model_copy(
            update={"decision": decision, "rationale": f"{result.rationale} [{override_reason}]"}
        )
    return result
