"""recall(query, session_id, token_budget): merges working + episodic +
semantic reads under one token budget.

Deliberately simple/greedy -- this is NOT the Context Assembly Service's
budget allocator (3-Context-Assembly-Service/src/budget/allocator.py), just
enough to answer "what should the agent see right now."

Reservation order (see docs/POLICIES.md "Recall packing"):
1. Working -- always included, newest-first, trimmed to `token_budget` if
   working's own current usage exceeds it (working has no session concept,
   see src/memory/working.py, so this isn't session-scoped).
2. Whatever budget remains: semantic facts, highest confidence first.
3. Whatever budget remains after that: episodic (keyword matches for the
   query, then most-recent), deduped.
A candidate that doesn't fit is skipped and packing for that tier stops
(no reordering to fit smaller items in later) -- that's the "simple" in
simple/greedy.

Must not: write to any of the three stores -- recall() is read-only,
unlike Orchestrator.tick().

Next: src/memory/ui.py -- the only current caller of recall().
"""

from pydantic import BaseModel, Field

from memory.episodic import Episode, EpisodicMemory
from memory.semantic import SemanticMemory
from memory.working import WorkingMemory, count_tokens


class ProvenanceEntry(BaseModel):
    id: str
    store: str  # "working" | "episodic" | "semantic"
    score: float | None = None  # only semantic search results carry a score


class PackedMemory(BaseModel):
    text: str
    token_count: int
    provenance: list[ProvenanceEntry] = Field(default_factory=list)


def _pack_working(working: WorkingMemory, remaining: int) -> tuple[str | None, int, list[ProvenanceEntry]]:
    newest_first = list(reversed(working.items()))
    included = []
    provenance = []
    for item in newest_first:
        if item.token_count > remaining:
            break
        included.append(item)
        remaining -= item.token_count
        provenance.append(ProvenanceEntry(id=item.id, store="working"))
    included.reverse()  # chronological order for display
    text = "\n".join(f"[{item.role}] {item.text}" for item in included) if included else None
    return text, remaining, provenance


def _pack_semantic(
    semantic: SemanticMemory,
    query: str,
    namespace: str,
    remaining: int,
    k: int,
    min_score: float,
) -> tuple[str | None, int, list[ProvenanceEntry]]:
    matches = semantic.search(query, namespace=namespace, k=k, min_score=min_score)
    matches.sort(key=lambda m: (m.fact.confidence, m.score), reverse=True)
    included = []
    provenance = []
    for match in matches:
        tokens = count_tokens(match.fact.text)
        if tokens > remaining:
            break
        included.append(match)
        remaining -= tokens
        provenance.append(ProvenanceEntry(id=match.fact.id, store="semantic", score=match.score))
    text = "\n".join(f"- {m.fact.text}" for m in included) if included else None
    return text, remaining, provenance


def _pack_episodic(
    episodic: EpisodicMemory,
    query: str,
    session_id: str,
    remaining: int,
    keyword_k: int,
    recent_n: int,
) -> tuple[str | None, int, list[ProvenanceEntry]]:
    keyword_hits = episodic.search_keyword(session_id, query, limit=keyword_k)
    recent = list(reversed(episodic.list(session_id)[-recent_n:]))  # newest first
    seen: set[str] = set()
    candidates: list[Episode] = []
    for ep in keyword_hits + recent:  # keyword relevance first, then recency
        if ep.id in seen:
            continue
        seen.add(ep.id)
        candidates.append(ep)

    included = []
    provenance = []
    for ep in candidates:
        if ep.token_count > remaining:
            break
        included.append(ep)
        remaining -= ep.token_count
        provenance.append(ProvenanceEntry(id=ep.id, store="episodic"))
    text = "\n".join(f"[{ep.type}] {ep.text}" for ep in included) if included else None
    return text, remaining, provenance


def recall(
    working: WorkingMemory,
    episodic: EpisodicMemory,
    semantic: SemanticMemory,
    query: str,
    session_id: str,
    token_budget: int,
    *,
    semantic_namespace: str | None = None,
    semantic_k: int = 5,
    semantic_min_score: float = 0.5,
    episodic_keyword_k: int = 5,
    episodic_recent_n: int = 5,
) -> PackedMemory:
    namespace = semantic_namespace or session_id
    remaining = token_budget
    sections: list[str] = []
    provenance: list[ProvenanceEntry] = []

    working_text, remaining, working_prov = _pack_working(working, remaining)
    if working_text:
        sections.append(working_text)
    provenance += working_prov

    semantic_text, remaining, semantic_prov = _pack_semantic(
        semantic, query, namespace, remaining, semantic_k, semantic_min_score
    )
    if semantic_text:
        sections.append(semantic_text)
    provenance += semantic_prov

    episodic_text, remaining, episodic_prov = _pack_episodic(
        episodic, query, session_id, remaining, episodic_keyword_k, episodic_recent_n
    )
    if episodic_text:
        sections.append(episodic_text)
    provenance += episodic_prov

    return PackedMemory(
        text="\n\n".join(sections),
        token_count=token_budget - remaining,
        provenance=provenance,
    )
