"""Streamlit UI for the Semantic Cache Layer (docs/ARCHITECTURE.md).

Thin wiring only -- business logic lives in src/cache, src/embed,
src/policy, src/metrics, src/providers. Run via run.cmd, or directly:

    uv run streamlit run src/ui/app.py
"""

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# `streamlit run` executes this file directly (not `python -m`), so the repo
# root isn't on sys.path by default and `from src...` below would fail --
# insert it manually before any src import.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from src.cache.models import CacheRecord, Hit, Miss
from src.cache.normalize import normalize_query
from src.cache.service import SemanticCache
from src.embed.ollama_client import DEFAULT_EMBED_MODEL, OllamaEmbedError, REBUILD_EMBED_MODEL
from src.metrics.aggregator import aggregate, read_events
from src.metrics.logger import DEFAULT_METRICS_PATH
from src.policy.enforcement import PolicyRejectedError
from src.providers.generate import PROVIDERS, GenerateError, generate
from src.store.index_meta import RebuildRequiredError, load_index_meta

load_dotenv()

st.set_page_config(page_title="Semantic Cache Layer", page_icon=":material/bolt:")

PROVIDER_LABELS = {
    "ollama": "Ollama",
    "agnes": "Agnes AI",
    "openai_compatible": "OpenAI-compatible",
    "gemini": "Gemini",
}


@st.cache_resource
def get_cache() -> SemanticCache:
    # Cached for the life of the server process (Streamlit re-runs this whole
    # script on every widget interaction) -- config/cache.yaml is therefore
    # only read once, at first load, not on each rerun (docs/RUNBOOK.md).
    return SemanticCache()


cache = get_cache()

st.title("Semantic Cache Layer")
st.caption("Embed the query, search Qdrant, return the stored answer on a hit.")

with st.sidebar:
    st.subheader("Settings")
    namespace = st.text_input("Namespace", value="demo", key="namespace")
    threshold = st.slider(
        "Similarity threshold",
        min_value=0.0,
        max_value=1.0,
        value=cache.score_threshold,
        step=0.01,
        key="threshold",
        help="Cosine similarity a lookup's top match must reach to count as a hit.",
    )
    embed_model = st.selectbox(
        "Embed model",
        [DEFAULT_EMBED_MODEL, REBUILD_EMBED_MODEL],
        key="embed_model",
    )

    index_meta = load_index_meta()
    if index_meta is not None and index_meta.embed_model != embed_model:
        st.warning(
            f"The index was built with `{index_meta.embed_model}` (dim "
            f"{index_meta.dim}). `{embed_model}` won't match it -- lookups "
            "and writes will fail until you switch back, or wipe and "
            "rebuild the index (docs/RUNBOOK.md).",
            icon=":material/warning:",
        )

# Works around get_cache() only constructing SemanticCache once: these two
# settings are re-applied to the cached instance on every rerun so the
# sidebar's slider/selectbox stay live without restarting the process.
cache.score_threshold = threshold
cache.embed_model = embed_model

st.subheader("Look up a query")
with st.form("lookup_form", border=False):
    query = st.text_input(
        "Query", placeholder="Ask something...", key="query_text", label_visibility="collapsed"
    )
    submitted = st.form_submit_button(
        "Lookup", icon=":material/search:", type="primary"
    )

if submitted and query.strip():
    try:
        result = cache.get(query, namespace=namespace)
    except RebuildRequiredError as exc:
        st.error(f"Index/embed-model mismatch: {exc}", icon=":material/error:")
    except OllamaEmbedError as exc:
        st.error(f"Ollama is unreachable: {exc}", icon=":material/error:")
    else:
        st.session_state["last_result"] = result
        st.session_state["last_query"] = query

# Streamlit re-runs this whole script on every interaction (e.g. clicking
# "Generate and store" below), which would otherwise drop the lookup result
# from view -- session_state is what keeps it displayed across that rerun.
result = st.session_state.get("last_result")
last_query = st.session_state.get("last_query")

if result is not None:
    if isinstance(result, Hit):
        st.success(f"Hit ({result.type})", icon=":material/check_circle:")
        st.metric("Score", f"{result.score:.4f}")
        st.text_input(
            "Matched query", value=result.matched_query, disabled=True, key="matched_query_display"
        )
        st.text_area("Answer", value=result.answer, disabled=True, key="answer_display")
    elif isinstance(result, Miss):
        st.warning("Miss", icon=":material/cancel:")
        if result.top1_score is not None:
            st.metric("Top-1 score (below threshold)", f"{result.top1_score:.4f}")
        else:
            st.caption("No candidates found in this namespace/embed model.")

        st.divider()
        st.subheader("Generate and store (demo)")
        st.caption(
            "Optional, demo only -- generation is not this repo's job "
            "(docs/ARCHITECTURE.md). Calls a real provider API."
        )
        with st.container(horizontal=True):
            gen_provider = st.selectbox(
                "Provider",
                list(PROVIDERS.keys()),
                format_func=lambda p: PROVIDER_LABELS[p],
                key="gen_provider",
            )
            gen_model = st.selectbox("Model", PROVIDERS[gen_provider], key="gen_model")

        if st.button("Generate and store", icon=":material/auto_awesome:", type="primary"):
            try:
                answer = generate(gen_provider, gen_model, last_query)
            except GenerateError as exc:
                st.error(f"Generation failed: {exc}", icon=":material/error:")
            else:
                record = CacheRecord(
                    id=str(uuid.uuid4()),
                    namespace=namespace,
                    query_raw=last_query,
                    query_norm=normalize_query(last_query),
                    answer=answer,
                    producer_model=gen_model,
                    provider=gen_provider,
                    created_at=datetime.now(timezone.utc),
                )
                try:
                    cache.put(record)
                except PolicyRejectedError as exc:
                    st.error(
                        f"Generated answer rejected by cache policy: {exc.reason}",
                        icon=":material/block:",
                    )
                except (RebuildRequiredError, OllamaEmbedError) as exc:
                    st.error(str(exc), icon=":material/error:")
                else:
                    st.success("Stored.", icon=":material/save:")
                    st.text_area("Generated answer", value=answer, disabled=True)

st.divider()
st.subheader("Metrics")

namespace_events = [e for e in read_events(DEFAULT_METRICS_PATH) if e.namespace == namespace]
stats = aggregate(namespace_events)
namespace_stats = stats.get(namespace)
hit_rate_display = (
    f"{namespace_stats.hit_rate:.1%}"
    if namespace_stats is not None and namespace_stats.hit_rate is not None
    else "—"
)
st.metric(f"Hit rate ({namespace})", hit_rate_display)

last_50 = namespace_events[-50:]
if last_50:
    events_df = pd.DataFrame([e.model_dump() for e in reversed(last_50)])
    st.dataframe(
        events_df,
        hide_index=True,
        width="stretch",
        column_config={
            "ts": st.column_config.DatetimeColumn("Time", format="HH:mm:ss"),
            "score": st.column_config.NumberColumn("Score", format="%.4f"),
            "latency_ms": st.column_config.NumberColumn("Latency (ms)", format="%.1f"),
            "embed_ms": st.column_config.NumberColumn("Embed (ms)", format="%.1f"),
        },
    )
else:
    st.caption(f"No metric events yet for namespace '{namespace}'.")

st.divider()
with st.container(horizontal=True):
    if st.button("Clear namespace", icon=":material/delete:"):
        removed = cache.clear(namespace)
        st.toast(f"Cleared {removed} entr{'y' if removed == 1 else 'ies'} from '{namespace}'.")
        st.session_state.pop("last_result", None)
        st.rerun()

    if DEFAULT_METRICS_PATH.exists():
        st.download_button(
            "Export metrics.jsonl",
            data=DEFAULT_METRICS_PATH.read_bytes(),
            file_name="metrics.jsonl",
            mime="application/x-ndjson",
            icon=":material/download:",
        )
    else:
        st.button("Export metrics.jsonl", disabled=True, icon=":material/download:")
