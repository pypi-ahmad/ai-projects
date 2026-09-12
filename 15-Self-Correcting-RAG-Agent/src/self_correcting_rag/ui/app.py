"""Streamlit UI: pick a corpus, ask a question, see the cited answer plus the
full rewrite -> retrieve -> critique -> branch trace. Ollama must be running
for the default (local) provider -- see SPEC.md.

This whole file reruns top to bottom on every widget interaction (Streamlit's execution
model) -- there is no server-side session state here beyond `get_provider`'s
`@st.cache_resource` cache (keyed by provider name, so switching providers doesn't reuse a
stale client) and each viewer's own browser-side widget state. A question's result is not
persisted anywhere; navigating away loses it.
"""

from pathlib import Path

import streamlit as st

from self_correcting_rag.agent.loop import run_safe
from self_correcting_rag.agent.rewrite import DEFAULT_REWRITE_MODEL
from self_correcting_rag.agent.schemas import LoopPolicy
from self_correcting_rag.config import load_settings
from self_correcting_rag.index.pipeline import run_index
from self_correcting_rag.llm.base import ProviderConfigError
from self_correcting_rag.llm.registry import PROVIDERS
from self_correcting_rag.web.base import WebSearch
from self_correcting_rag.web.http_fetch import HttpWebFetch
from self_correcting_rag.web.http_search import DEFAULT_BASE_URL, HttpSearch
from self_correcting_rag.web.null_search import NullSearch

DEFAULT_INDEX_DIR = Path("data/indexes")
DEFAULT_INGEST_DIR = "data/raw/wiki"

st.set_page_config(page_title="Self-Correcting RAG Agent", page_icon=":material/psychology:")


@st.cache_resource
def get_provider(name: str):
    return PROVIDERS[name].factory()


st.title("Self-correcting RAG agent")
st.caption("Query rewrite → hybrid retrieve → critique → answer, retry, web fallback, or abstain.")

settings = load_settings()

with st.sidebar:
    st.subheader("Corpus")
    ingest_dir = st.text_input("Ingest folder path", value=DEFAULT_INGEST_DIR)
    if st.button("Re-index this folder", width="stretch"):
        with st.spinner("Indexing..."):
            try:
                count = run_index(Path(ingest_dir), DEFAULT_INDEX_DIR)
                st.success(f"Indexed {count} chunk(s) from {ingest_dir}.")
            except Exception as e:
                st.error(f"Indexing failed: {e}")

    st.subheader("Provider & models")
    provider_names = sorted(PROVIDERS)
    provider_name = st.selectbox(
        "Provider", options=provider_names, index=provider_names.index("ollama")
    )
    spec = PROVIDERS[provider_name]
    model_options = list(spec.allowed_models)
    answer_model = st.selectbox(
        "Answer model", options=model_options, index=model_options.index(spec.default_model)
    )
    rewrite_default_index = (
        model_options.index(DEFAULT_REWRITE_MODEL) if DEFAULT_REWRITE_MODEL in model_options else 0
    )
    rewrite_critique_model = st.selectbox(
        "Rewrite / critique model", options=model_options, index=rewrite_default_index
    )

    st.subheader("Loop settings")
    max_iters = st.slider("Max iterations", min_value=1, max_value=4, value=2)
    confidence_threshold = st.slider(
        "Confidence threshold", min_value=0.0, max_value=1.0, value=0.6, step=0.05
    )
    web_requested = st.toggle("Enable web fallback", value=False)
    web_enabled = settings.resolve_web_enabled(web_requested)
    if web_requested and not web_enabled:
        st.warning(
            "SEARCH_API_KEY is not set -- web fallback is forced off.", icon=":material/warning:"
        )

with st.form("ask_form"):
    question = st.text_area("Question", height=100, placeholder="How many vacation days do I get?")
    submitted = st.form_submit_button("Ask", type="primary")

if submitted and question.strip():
    try:
        provider = get_provider(provider_name)
    except ProviderConfigError as e:
        st.error(f"{provider_name} isn't configured: {e}")
        st.stop()

    web_search: WebSearch = (
        HttpSearch(
            api_key=settings.search_api_key, base_url=settings.search_base_url or DEFAULT_BASE_URL
        )
        if web_enabled and settings.search_api_key
        else NullSearch()
    )

    policy = LoopPolicy(
        confidence_threshold=confidence_threshold, max_iters=max_iters, web_enabled=web_enabled
    )

    with st.spinner("Rewriting, retrieving, and critiquing..."):
        result = run_safe(
            question,
            index_dir=DEFAULT_INDEX_DIR,
            provider=provider,
            rewrite_model=rewrite_critique_model,
            critique_model=rewrite_critique_model,
            answer_model=answer_model,
            policy=policy,
            web_search=web_search,
            web_fetch=HttpWebFetch(),
        )

    branch = next(
        (s.detail.get("decision") for s in reversed(result.trace.steps) if s.stage == "critique"),
        None,
    )

    if result.answer:
        st.markdown(result.answer)
        cols = st.columns(2)
        cols[0].metric(
            "Confidence", f"{result.confidence:.2f}" if result.confidence is not None else "n/a"
        )
        cols[1].metric("Branch", branch or "answer")
        if result.citations:
            st.caption("Citations: " + ", ".join(result.citations))
    else:
        st.warning(f"Abstained ({branch or 'abstain'}): {result.reason}", icon=":material/block:")

    with st.expander("Rewrite queries, retrieved scores, critique JSON"):
        for step in result.trace.steps:
            st.markdown(f"**Iteration {step.iteration} — {step.stage}**")
            if step.stage == "rewrite":
                for q in step.detail.get("queries", []):
                    st.write(f"- {q}")
                st.caption(step.summary)
            elif step.stage == "retrieve":
                chunks = step.detail.get("chunks", [])
                if chunks:
                    st.dataframe(chunks, width="stretch", hide_index=True)
                else:
                    st.caption(step.summary)
            elif step.stage == "critique":
                st.json(step.detail)
            elif step.stage == "web":
                st.write(step.summary)
                if step.detail.get("urls"):
                    for url in step.detail["urls"]:
                        st.write(f"- {url}")
            elif step.stage in ("generate", "error"):
                st.write(step.summary)
                if step.detail:
                    st.json(step.detail)
            st.divider()

    st.subheader("Trace timeline")
    st.dataframe(
        [
            {"iteration": s.iteration, "stage": s.stage, "summary": s.summary}
            for s in result.trace.steps
        ],
        width="stretch",
        hide_index=True,
    )
elif submitted:
    st.warning("Enter a question first.")
