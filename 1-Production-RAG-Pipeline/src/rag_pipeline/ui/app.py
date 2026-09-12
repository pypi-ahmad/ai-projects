"""Streamlit UI: sidebar config + Ingest / Query / Index status / Eval tabs.

Run via: uv run python -m streamlit run src/rag_pipeline/ui/app.py
"""

from pathlib import Path

import ollama
import streamlit as st

from rag_pipeline.chunk.pipeline import run_chunk
from rag_pipeline.config import load_settings
from rag_pipeline.eval.pipeline import run_eval
from rag_pipeline.generate.pipeline import run_generate
from rag_pipeline.generate.providers.base import ProviderConfigError
from rag_pipeline.generate.providers.registry import PROVIDERS
from rag_pipeline.index.pipeline import EMBED_MODELS, run_index
from rag_pipeline.ingest.pipeline import run_ingest

st.set_page_config(page_title="Local RAG Pipeline", layout="wide")

DEFAULT_INDEX_DIR = Path("data/indexes")
DEFAULT_INPUT_DIR = Path("data/raw")
DEFAULT_PROCESSED_DIR = Path("data/processed")
DEFAULT_QA_PATH = Path("data/eval/qa.jsonl")


def _ollama_installed_models() -> set[str]:
    """Live-detected models actually pulled in Ollama right now, not the
    static allowlist -- a model can be allowed but not pulled yet.
    """
    try:
        response = ollama.Client(host=load_settings().ollama_host).list()
        return {m.model for m in response.models if m.model}
    except Exception:
        return set()


# ---- Sidebar --------------------------------------------------------------

st.sidebar.header("Configuration")

provider = st.sidebar.selectbox("Provider", list(PROVIDERS), index=0)
spec = PROVIDERS[provider]

if provider == "ollama":
    installed = _ollama_installed_models()
    available_models = [m for m in spec.allowed_models if m in installed] or list(
        spec.allowed_models
    )
    if not installed:
        st.sidebar.warning("Could not detect Ollama models -- is Ollama running?")
else:
    available_models = list(spec.allowed_models)

model = st.sidebar.selectbox("Model", available_models, index=0)

embed_model = st.sidebar.radio(
    "Embed model (indexing only)", EMBED_MODELS, index=0, help="0.6b is the VRAM-safe default."
)
hybrid = st.sidebar.toggle("Hybrid retrieval (dense + BM25)", value=True)
rerank = st.sidebar.toggle("Rerank (qwen3.5:0.8b)", value=True)
top_k = st.sidebar.number_input("Top-k", min_value=1, max_value=20, value=5)
input_dir = st.sidebar.text_input("Input folder (for Ingest)", value=str(DEFAULT_INPUT_DIR))

st.sidebar.caption(f"Index: `{DEFAULT_INDEX_DIR}`")

tab_ingest, tab_query, tab_status, tab_eval = st.tabs(["Ingest", "Query", "Index status", "Eval"])

# ---- Ingest tab -------------------------------------------------------------

with tab_ingest:
    st.subheader("Ingest -> chunk -> index")
    st.text_input("Folder to ingest", value=input_dir, key="ingest_folder", disabled=True)
    if st.button("Run ingest -> chunk -> index", type="primary"):
        status = st.status("Running pipeline...", expanded=True)
        try:
            status.write(f"Ingesting `{input_dir}`...")
            ingest_path = run_ingest(Path(input_dir), DEFAULT_PROCESSED_DIR)
            status.write(f"Wrote `{ingest_path}`.")

            status.write("Chunking...")
            chunks_path = DEFAULT_PROCESSED_DIR / "chunks.jsonl"
            run_chunk(DEFAULT_PROCESSED_DIR, chunks_path)
            status.write(f"Wrote `{chunks_path}`.")

            status.write(f"Embedding + indexing (model: {embed_model})...")
            report = run_index(chunks_path, DEFAULT_INDEX_DIR, embed_model=embed_model)
            status.write(
                f"Indexed {report.chunk_count} chunks "
                f"({report.embedded_count} embedded, {report.skipped_count} unchanged)."
            )
            status.update(label="Done.", state="complete")
        except Exception as exc:  # noqa: BLE001 -- surface any pipeline failure to the UI, don't crash it
            status.update(label="Failed.", state="error")
            status.write(f"Error: {exc}")

# ---- Query tab --------------------------------------------------------------

with tab_query:
    st.subheader("Ask a question")
    question = st.text_input("Question", key="question")
    if st.button("Ask") and question:
        with st.spinner("Retrieving and generating..."):
            try:
                result = run_generate(
                    DEFAULT_INDEX_DIR,
                    question,
                    provider=provider,
                    model=model,
                    k=top_k,
                    hybrid=hybrid,
                    rerank=rerank,
                )
            except (ProviderConfigError, ValueError, RuntimeError) as exc:
                st.error(str(exc))
                result = None

        if result is not None:
            st.markdown(result.answer_markdown)
            st.caption(f"Model: `{result.model}` · Latency: {result.latency_ms:.0f} ms")

            if result.citations:
                st.write("**Citations**")
                for c in result.citations:
                    if st.button(
                        f"[S{c['index']}] {c['source_path']}, page {c['page']}",
                        key=f"cite_{c['index']}_{c['chunk_id']}",
                    ):
                        st.session_state["highlight_chunk_id"] = c["chunk_id"]

            with st.expander("Retrieved chunks and scores", expanded=False):
                highlighted = st.session_state.get("highlight_chunk_id")
                for trace in result.retrieval_trace:
                    marker = "**-> ** " if trace["chunk_id"] == highlighted else ""
                    st.markdown(
                        f"{marker}`{trace['source_path']}` page {trace['page']} — "
                        f"fusion_rank={trace['fusion_rank']}, score={trace['score']:.4f}, "
                        f"rerank_score={trace['rerank_score']}"
                    )

# ---- Index status tab -------------------------------------------------------

with tab_status:
    st.subheader("Index status")
    meta_path = DEFAULT_INDEX_DIR / "index_meta.json"
    chunks_path = DEFAULT_PROCESSED_DIR / "chunks.jsonl"
    if meta_path.exists():
        st.json(meta_path.read_text(encoding="utf-8"))
    else:
        st.info("No index yet -- run Ingest first.")
    if chunks_path.exists():
        n_chunks = sum(1 for line in chunks_path.open(encoding="utf-8") if line.strip())
        st.metric("Chunks in chunks.jsonl", n_chunks)
    qdrant_dir = DEFAULT_INDEX_DIR / "qdrant_db"
    bm25_dir = DEFAULT_INDEX_DIR / "bm25"
    st.write(f"Qdrant store present: {qdrant_dir.exists()}")
    st.write(f"BM25 store present: {bm25_dir.exists()}")

# ---- Eval tab ----------------------------------------------------------------

with tab_eval:
    st.subheader("Evaluation")
    qa_path_str = st.text_input("qa.jsonl path", value=str(DEFAULT_QA_PATH))
    use_judge = st.toggle("Score faithfulness with a judge model (extra Ollama calls)", value=False)
    judge_model = "qwen3.5:2b" if use_judge else None

    if st.button("Run eval"):
        qa_path = Path(qa_path_str)
        if not qa_path.exists():
            st.error(f"{qa_path} does not exist.")
        else:
            with st.spinner("Running eval cases..."):
                try:
                    report = run_eval(
                        DEFAULT_INDEX_DIR,
                        qa_path,
                        provider=provider,
                        model=model,
                        k=top_k,
                        judge_model=judge_model,
                    )
                except Exception as exc:  # noqa: BLE001 -- surface, don't crash the UI
                    st.error(f"Eval failed: {exc}")
                    report = None

            if report is not None:
                col1, col2, col3, col4 = st.columns(4)
                col1.metric(f"recall@{report.k}", f"{report.mean_recall_at_k}")
                col2.metric("citation hit rate", f"{report.mean_citation_hit_rate}")
                col3.metric("mean latency (ms)", f"{report.mean_latency_ms:.0f}")
                if report.judge_model:
                    col4.metric("faithfulness", f"{report.mean_faithfulness}")
                st.dataframe([vars(c) for c in report.cases])
