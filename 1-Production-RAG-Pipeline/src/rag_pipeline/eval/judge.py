"""Optional LLM-as-judge faithfulness scoring. Off by default -- only runs
when a judge model is explicitly passed (spec default: qwen3.5:2b).
"""

import logging
import re

import ollama

logger = logging.getLogger(__name__)

DEFAULT_JUDGE_MODEL = "qwen3.5:2b"
_NUMBER_RE = re.compile(r"[-+]?\d*\.?\d+")


def score_faithfulness(
    client: ollama.Client, judge_model: str, question: str, context: str, answer: str
) -> float | None:
    """Asks the judge model whether `answer` is fully supported by `context`
    (not the question -- faithfulness is answer-vs-context, not answer-vs-
    question relevance, which is what reranking already measures).
    """
    prompt = (
        "You are checking whether an answer is faithful to (fully supported by) the "
        "given context, with no unsupported claims added. Score from 0.0 (not "
        "supported at all) to 1.0 (fully supported). Respond with only the number.\n\n"
        f"Question: {question}\n\nContext:\n{context}\n\nAnswer:\n{answer}"
    )
    response = client.generate(model=judge_model, prompt=prompt)
    match = _NUMBER_RE.search(response.response or "")
    if not match:
        logger.warning("could not parse a faithfulness score from judge output")
        return None
    try:
        return max(0.0, min(1.0, float(match.group())))
    except ValueError:
        return None
