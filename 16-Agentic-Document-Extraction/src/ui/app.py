"""Streamlit front end for the active graph: upload a document, run
`run_graph` (preprocess -> parse -> END), and show the Markdown/HTML
preview, annotated PDF, parse JSON, and per-page API diagnostics.

This is a Streamlit script, not a library module: everything at module
level (including the widget calls in the sidebar) re-runs top-to-bottom on
every user interaction. Must not: assume a variable set earlier in one run
survives into the next without going through `st.session_state`, and must
not perform a model call or other side effect outside a button/condition
guard -- a bare top-level call would fire on every rerun, not just on user
action.

Next: src/ui/clipboard.py for the custom copy-to-clipboard component used in
the Markdown preview tab.
"""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from src import usage
from src.models import MODEL_RATES
from src.graph import run_graph
from src.markdown import parse_to_html
from src.preprocess import count_pages
from src.schema import ParseResult
from src.ui.clipboard import copy_buttons

INBOX_DIR = Path("data/inbox")
PARSE_DIR = Path("data/parse")

st.set_page_config(page_title="ADE - Document Parsing", layout="wide")
st.title("ADE - Agentic Document Extraction")

st.session_state.setdefault("session_token_usage", [])

_usage_display = st.empty()


def show_usage():
    totals = usage.totals(st.session_state.session_token_usage)
    incomplete = any(not entry.get("usage_known", True) for entry in st.session_state.session_token_usage)
    label = "Reported " if incomplete else ""
    with _usage_display.container():
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(f"{label}Input tokens (session)", f"{totals['input_tokens']:,}")
        c2.metric(f"{label}Cached input tokens", f"{totals['cached_tokens']:,}")
        c3.metric(f"{label}Output tokens", f"{totals['output_tokens']:,}")
        c4.metric(f"{label}Session cost", f"${usage.session_cost_usd(st.session_state.session_token_usage):.4f}")
        if incomplete:
            st.caption("Some requests did not report usage. Totals and estimated cost exclude unknown usage.")


show_usage()
st.divider()

st.session_state.setdefault("start_page_input", 1)
st.session_state.setdefault("end_page_input", 0)

# Detect a newly uploaded file's page count and seed the page-range widgets
# *before* they're instantiated below -- Streamlit forbids writing to a
# widget's session_state key after that widget has already run this pass,
# and st.session_state["uploader"] already reflects this run's upload
# (Streamlit restores widget state before executing the script), even
# though the st.file_uploader(...) call itself happens later, in the tab.
_pending_upload = st.session_state.get("uploader")
if _pending_upload is not None:
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    _dest = INBOX_DIR / _pending_upload.name
    # Only re-save the file and re-count pages the first time this exact
    # upload is seen; otherwise every rerun (e.g. moving the page-range
    # slider) would re-write the file and re-open the PDF pointlessly.
    if st.session_state.get("detected_pages_for") != str(_dest):
        _dest.write_bytes(_pending_upload.getvalue())
        try:
            _total = count_pages(_dest)
        except Exception:
            _total = 1
        st.session_state["detected_total_pages"] = _total
        st.session_state["detected_pages_for"] = str(_dest)
        st.session_state["start_page_input"] = 1
        st.session_state["end_page_input"] = _total

with st.sidebar:
    st.header("Options")
    selected_model = st.selectbox(
        "Model", list(MODEL_RATES), key="selected_model",
        format_func=lambda model: "GPT-5.6 Terra" if model.endswith("terra") else "GPT-5.6 Luna",
    )
    detected_total = st.session_state.get("detected_total_pages")
    if detected_total:
        st.caption(f"Detected {detected_total} page(s) in the uploaded file.")
    start_page = st.number_input("Start page", min_value=1, step=1, key="start_page_input")
    end_page_raw = st.number_input("End page", min_value=0, step=1, key="end_page_input")
    end_page = int(end_page_raw) or None
    st.divider()
    uploaded = st.file_uploader(
        "Upload a document", type=["png", "jpg", "jpeg", "webp", "tif", "tiff", "pdf"], key="uploader"
    )

if uploaded is not None:
    dest = INBOX_DIR / uploaded.name
    st.success(f"Saved to {dest}")

    if st.button("Parse"):
        with st.spinner("Parsing..."):
            try:
                result = run_graph(str(dest), start_page=int(start_page), end_page=end_page, model=selected_model)
            except Exception as exc:
                st.error(str(exc))
                result = None

        st.session_state["last_parse_result"] = result
        st.session_state["last_parse_path"] = str(dest)
        if result:
            st.session_state.session_token_usage.extend(result.get("token_usage", []))
            show_usage()

    # Only show a previously-run result if it belongs to *this* uploaded
    # file -- otherwise selecting a new file would keep showing the last
    # file's result until Parse is clicked again.
    result = st.session_state.get("last_parse_result") if st.session_state.get("last_parse_path") == str(dest) else None
    if result:
        status = result.get("status")
        st.subheader(f"Status: {status}")
        st.caption(f"Result model: {result.get('model', 'gpt-5.6-terra')}")
        parse_error = result.get("parse_error")
        if parse_error:
            label = (
                "Layout parsing incomplete"
                if status == "parsed_partial"
                else "Layout parsing failed"
            )
            st.warning(f"{label}: {parse_error}")

        doc_sha = result.get("doc_sha")
        current_parse = result.get("parse_result")
        if current_parse and current_parse.page_diagnostics:
            with st.expander("API diagnostics", expanded=False):
                st.json([d.model_dump(exclude_none=True) for d in current_parse.page_diagnostics])
                if any(d.outcome != "parsed" and not d.filters for d in current_parse.page_diagnostics):
                    st.caption("Filter details are unavailable for one or more failed pages. The provider did not supply recognized annotations.")
        markdown_path = (
            PARSE_DIR / f"{doc_sha}.md" if doc_sha and result.get("markdown") is not None else None
        )
        parse_json_path = PARSE_DIR / f"{doc_sha}.json" if doc_sha and current_parse is not None else None
        annotated_pdf_path = result.get("annotated_pdf_path")
        annotated_pages_dir = Path(annotated_pdf_path).parent / doc_sha if annotated_pdf_path else None

        tab_markdown, tab_html, tab_pdf, tab_parse_json = st.tabs(
            ["Markdown preview", "Formatted preview", "Annotated PDF", "Parse JSON"]
        )

        with tab_markdown:
            if markdown_path and markdown_path.exists():
                md_text = markdown_path.read_text(encoding="utf-8")
                st.download_button(
                    "Download Markdown", data=md_text, file_name=markdown_path.name,
                    mime="text/markdown", key=f"{doc_sha}_download_md",
                    on_click="ignore",
                )
                rendered_html = parse_to_html(current_parse)
                copy_buttons(
                    data={"markdown": md_text, "html": rendered_html},
                    key=f"{doc_sha}_copy", height="content",
                )
                preview_body = rendered_html.split("<body>", 1)[1].rsplit("</body>", 1)[0]
                st.html(preview_body)
            else:
                st.info("No layout parse markdown available for this document.")

        with tab_html:
            if parse_json_path and parse_json_path.exists():
                parse_result = ParseResult.model_validate_json(parse_json_path.read_text(encoding="utf-8"))
                components.html(parse_to_html(parse_result), height=800, scrolling=True)
            else:
                st.info("No parse result available to render.")

        with tab_pdf:
            if annotated_pdf_path and Path(annotated_pdf_path).exists():
                st.download_button(
                    "Download annotated PDF", data=Path(annotated_pdf_path).read_bytes(),
                    file_name=Path(annotated_pdf_path).name, mime="application/pdf",
                    key=f"{doc_sha}_download_pdf",
                )
                if annotated_pages_dir and annotated_pages_dir.exists():
                    for page_png in sorted(annotated_pages_dir.glob("page_*.png")):
                        st.image(str(page_png), caption=page_png.stem)
            else:
                st.info("No annotated PDF available for this document.")

        with tab_parse_json:
            if parse_json_path and parse_json_path.exists():
                parse_json_text = parse_json_path.read_text(encoding="utf-8")
                st.download_button(
                    "Download parse JSON", data=parse_json_text, file_name=parse_json_path.name,
                    mime="application/json", key=f"{doc_sha}_download_parse_json",
                )
                st.json(json.loads(parse_json_text))
            else:
                st.info("No parse JSON available for this document.")
