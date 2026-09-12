"""Streamlit inspector for working/episodic/semantic memory + optional debug chat.

One shared WorkingMemory per running app process -- it has no session_id
concept (see src/memory/working.py), so the sidebar's Session ID only
partitions episodic and semantic memory, not the working buffer.

If Ollama is unreachable, SemanticMemory() raises at construction time;
this page catches that, shows a banner, and keeps working/episodic memory
fully usable. Use "Retry connection" once Ollama is back up.

Must not: assume `semantic` is non-None below that try/except -- every
semantic-dependent code path (Orchestrator construction, Recall, Facts
pane, Facts metric) has its own `if semantic` guard.

Next: scripts/seed_demo.py -- a non-UI caller exercising the same stores.
"""

from datetime import datetime, timezone

import streamlit as st

from memory.episodic import Episode, EpisodicMemory
from memory.orchestrator import Orchestrator
from memory.recall import recall
from memory.semantic import SemanticMemory
from memory.working import WorkingItem, WorkingMemory

st.set_page_config(page_title="Agent Memory System", layout="wide")


@st.cache_resource
def _working() -> WorkingMemory:
    wm = WorkingMemory()
    wm.load()  # restore data/memory/working.json if a prior run left one
    return wm


@st.cache_resource
def _episodic() -> EpisodicMemory:
    return EpisodicMemory()


@st.cache_resource
def _semantic() -> SemanticMemory | None:
    try:
        return SemanticMemory()
    except Exception as exc:  # Ollama down, RebuildRequiredError, etc.
        st.session_state["semantic_error"] = str(exc)
        return None


working = _working()
episodic = _episodic()
semantic = _semantic()

st.sidebar.title("Agent memory system")
session_id = st.sidebar.text_input("Session ID", value="default")
st.sidebar.caption("Episodic and semantic memory are scoped to this session. Working memory is shared by the whole app.")

if semantic is None:
    col1, col2 = st.columns([5, 1])
    with col1:
        st.warning(
            "Semantic memory is unavailable -- Ollama looks unreachable "
            f"({st.session_state.get('semantic_error', 'unknown error')}). "
            "Working and episodic memory still work; recall will skip facts."
        )
    with col2:
        if st.button("Retry connection"):
            _semantic.clear()
            st.rerun()

orchestrator = Orchestrator(working, episodic, semantic, session_id) if semantic else None

st.header("Append")
role_col, text_col, button_col = st.columns([1, 4, 1])
with role_col:
    role = st.selectbox("Role", ["user", "assistant", "tool", "system"], label_visibility="collapsed")
with text_col:
    append_text = st.text_input("Text", key="append_text", label_visibility="collapsed", placeholder="Say something...")
with button_col:
    if st.button("Append", width="stretch") and append_text:
        working.append(WorkingItem.create(role, append_text))
        working.snapshot()
        st.rerun()

st.header("Tick")
tick_col, distill_col = st.columns(2)
with tick_col:
    if st.button("tick()", width="stretch", disabled=orchestrator is None):
        report = orchestrator.tick()
        working.snapshot()  # tick's step 1 may have evicted working items
        st.session_state["last_report"] = report.model_dump()
        st.session_state["last_tick_at"] = datetime.now(timezone.utc).strftime("%H:%M:%S")
with distill_col:
    if st.button("tick(distill=True)", width="stretch", disabled=orchestrator is None):
        report = orchestrator.tick(distill=True)
        working.snapshot()
        st.session_state["last_report"] = report.model_dump()
        st.session_state["last_tick_at"] = datetime.now(timezone.utc).strftime("%H:%M:%S")

if "last_report" in st.session_state:
    st.json(st.session_state["last_report"])

st.header("Recall")
query = st.text_input("Query", key="recall_query", placeholder="What do you want to remember?")
token_budget = st.number_input("Token budget", min_value=50, value=800, step=50)
if st.button("Recall") and query:
    packed = recall(working, episodic, semantic, query, session_id, int(token_budget)) if semantic else None
    if packed is None:
        st.error("Semantic memory is unavailable -- recall needs it.")
    else:
        st.text_area("Packed memory", packed.text, height=200, label_visibility="collapsed")
        st.caption(f"{packed.token_count} / {int(token_budget)} tokens")
        st.dataframe([p.model_dump() for p in packed.provenance], width="stretch")

st.header("Panes")
working_pane, episode_pane, fact_pane = st.columns(3)

with working_pane, st.container(border=True):
    st.subheader("Working")
    used = working.total_tokens()
    st.progress(min(used / working.token_cap, 1.0), text=f"{used} / {working.token_cap} tokens")
    for item in reversed(working.items()):
        st.text(f"[{item.role}] {item.text[:80]}")

with episode_pane, st.container(border=True):
    st.subheader("Episodes")
    episodes: list[Episode] = episodic.list(session_id)
    st.caption(f"{len(episodes)} total")
    for ep in reversed(episodes[-20:]):
        st.text(f"[{ep.type}] {ep.text[:80]}")

with fact_pane, st.container(border=True):
    st.subheader("Facts")
    if semantic is None:
        st.caption("disabled -- Ollama unreachable")
    elif query:
        matches = semantic.search(query, namespace=session_id, k=10)
        st.caption(f"{len(matches)} matches for {query!r}")
        for m in matches:
            st.text(f"{m.score:.2f}  {m.fact.text[:80]}")
    else:
        st.caption("enter a query above to see fact matches")

st.header("Metrics")
m1, m2, m3, m4 = st.columns(4)
m1.metric("Working tokens", f"{working.total_tokens()} / {working.token_cap}")
m2.metric("Episodes", len(episodic.list(session_id)))
m3.metric("Facts", semantic.count(session_id) if semantic else "n/a")
m4.metric("Last tick", st.session_state.get("last_tick_at", "never"))
