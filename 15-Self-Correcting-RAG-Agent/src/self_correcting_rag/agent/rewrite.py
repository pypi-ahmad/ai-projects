"""Query rewrite: turn the raw user query into 1-3 retrieval-shaped queries."""

from self_correcting_rag.agent.json_llm import call_json
from self_correcting_rag.agent.prompts import REWRITE_SYSTEM_PROMPT
from self_correcting_rag.agent.schemas import RewriteResult
from self_correcting_rag.llm.base import Provider

DEFAULT_REWRITE_MODEL = "qwen3.5:0.8b"


def rewrite(
    provider: Provider, model: str, query: str, hints: list[str] | None = None
) -> RewriteResult:
    user = query
    if hints:
        user = (
            f"{query}\n\nA previous retrieval attempt was missing: {'; '.join(hints)}. "
            "Prefer rewrites that would surface this."
        )
    return call_json(
        provider, system=REWRITE_SYSTEM_PROMPT, user=user, model=model, schema=RewriteResult
    )
