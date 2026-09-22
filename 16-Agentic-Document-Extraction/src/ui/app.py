"""Single-model document UI. Only an explicit Parse click calls the model."""
from __future__ import annotations

import base64
import hashlib
from pathlib import Path

import streamlit as st

from src import usage
from src.models import DEFAULT_MODEL
from src.graph import run_graph
from src.markdown import parse_to_html
from src.preprocess import count_pages, preprocess_pages
from src.ui.clipboard import copy_buttons

INBOX_DIR = Path("data/inbox")
st.set_page_config(page_title="ADE - Document Parsing", layout="wide")
st.title("ADE - Agentic Document Extraction")

if st.session_state.get("usage_model_version") != DEFAULT_MODEL:
    if st.session_state.get("session_token_usage"):
        st.info("Started a new Sol usage ledger. Previous model usage has not been repriced.")
    st.session_state["session_token_usage"] = []
    st.session_state["usage_model_version"] = DEFAULT_MODEL
    st.session_state.pop("last_parse_result", None)

_usage_display = st.empty()


@st.cache_data(max_entries=8, show_spinner=False)
def load_input_preview(path: str, start_page: int, end_page: int) -> list[tuple[int, bytes]]:
    return [
        (page["page"], base64.b64decode(page["base64"]))
        for page in preprocess_pages(path, start_page=start_page, end_page=end_page)
    ]


def show_usage():
    entries = st.session_state.session_token_usage
    totals = usage.totals(entries)
    incomplete = any(not entry.get("usage_known", True) for entry in entries)
    label = "Reported " if incomplete else ""
    with _usage_display.container():
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric(f"{label}Input tokens (session)", f"{totals['input_tokens']:,}")
        c2.metric(f"{label}Cached input tokens", f"{totals['cached_tokens']:,}")
        c3.metric(f"{label}Cache-write tokens", f"{totals['cache_write_tokens']:,}")
        c4.metric(f"{label}Output tokens", f"{totals['output_tokens']:,}")
        c5.metric(f"{label}Session cost", f"${usage.session_cost_usd(entries):.4f}")
        if incomplete:
            st.caption("Some requests did not report usage. Totals and estimated cost exclude unknown usage.")


show_usage()
st.divider()
with st.sidebar:
    st.header("Options")
    st.caption("Model: GPT-6 Sol")
    uploaded = st.file_uploader(
        "Upload a document", type=["png", "jpg", "jpeg", "webp", "tif", "tiff", "pdf"], key="uploader"
    )
    if uploaded is None:
        st.stop()
    raw = uploaded.getvalue()
    upload_id = hashlib.sha256(raw).hexdigest() + Path(uploaded.name).suffix.lower()
    dest = INBOX_DIR / upload_id
    if st.session_state.get("upload_id") != upload_id:
        st.session_state["upload_id"] = upload_id
        st.session_state.pop("last_parse_result", None)
        st.session_state["upload_error"] = None
        try:
            INBOX_DIR.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(raw)
            total = count_pages(dest)
            if total < 1:
                raise ValueError("Document contains no pages")
            st.session_state["detected_total_pages"] = total
            st.session_state["start_page_input"] = 1
            st.session_state["end_page_input"] = total
        except Exception:
            st.session_state["upload_error"] = "Cannot read this document. Upload a valid image or PDF."
    if st.session_state.get("upload_error"):
        st.error(st.session_state["upload_error"])
        st.stop()
    total = st.session_state["detected_total_pages"]
    st.caption(f"Detected {total} page(s) in the uploaded file.")
    start_page = st.number_input("Start page", min_value=1, step=1, key="start_page_input")
    end_page_raw = st.number_input("End page", min_value=0, step=1, key="end_page_input")
    end_page = int(end_page_raw) or total

st.caption(f"Document: {uploaded.name}")
valid_range = 1 <= start_page <= end_page <= total
if not valid_range:
    st.error(f"Page range must be within 1..{total}, with start no greater than end.")

if st.button("Parse", disabled=not valid_range):
    progress = st.progress(0, text="Preparing pages...")

    def update_progress(event):
        progress.progress(event["completed"] / event["total"], text=(
            f"Pages: {event['completed']}/{event['total']} completed; "
            f"{event['successful']} successful; {event['failed']} failed"
        ))

    with st.spinner("Parsing..."):
        try:
            result = run_graph(str(dest), start_page=int(start_page), end_page=end_page,
                               model=DEFAULT_MODEL, on_progress=update_progress)
        except Exception:
            st.error("Unable to prepare this document. Check the file and page range.")
            result = None
    st.session_state["last_parse_result"] = result
    if result:
        st.session_state.session_token_usage.extend(result.get("token_usage", []))
        show_usage()

result = st.session_state.get("last_parse_result")
if result:
    status = result.get("status")
    st.subheader(f"Status: {status}")
    st.caption(f"Result model: {result.get('model', DEFAULT_MODEL)}")
    if result.get("parse_error"):
        label = "Layout parsing incomplete" if status == "parsed_partial" else "Layout parsing failed"
        st.warning(f"{label}: {result['parse_error']}")
    current_parse = result.get("parse_result")
    if current_parse and current_parse.page_diagnostics:
        with st.expander("API diagnostics", expanded=False):
            st.json([d.model_dump(exclude_none=True) for d in current_parse.page_diagnostics])
            if any(d.outcome != "parsed" and not d.filters for d in current_parse.page_diagnostics):
                st.caption("Filter details are unavailable for one or more failed pages. The provider did not supply recognized annotations.")
else:
    current_parse = None

doc_sha = result.get("doc_sha", "document") if result else "document"
run_id = result.get("run_id", doc_sha) if result else upload_id
tab_input, tab_md, tab_pdf, tab_html, tab_json = st.tabs(
    ["Input preview", "Markdown", "Annotated", "HTML", "JSON"],
    key="preview_tab", on_change="rerun",
)

if tab_input.open:
    with tab_input:
        try:
            for page_number, image_bytes in load_input_preview(str(dest), int(start_page), end_page):
                st.image(image_bytes, caption=f"Page {page_number}")
        except Exception:
            st.error("Unable to render the selected input pages.")

if tab_md.open:
    with tab_md:
        md_text = result.get("markdown") if result else None
        if md_text is not None and current_parse:
            rendered_html = parse_to_html(current_parse)
            st.download_button("Download Markdown", data=md_text, file_name=f"{doc_sha}.md",
                               mime="text/markdown", key=f"{run_id}_download_md", on_click="ignore")
            copy_buttons(data={"markdown": md_text, "html": rendered_html},
                         key=f"{run_id}_copy_md", height="content")
            markdown_view = st.segmented_control(
                "Markdown view", ["Rendered", "Raw"], default="Rendered",
                key=f"{run_id}_markdown_view",
            )
            if markdown_view == "Raw":
                st.code(md_text, language="markdown", wrap_lines=True, height=500)
            else:
                st.markdown(md_text)
        else:
            st.info("Parse the document to create Markdown.")

if tab_pdf.open:
    with tab_pdf:
        pdf_path = result.get("annotated_pdf_path") if result else None
        if pdf_path and Path(pdf_path).is_file():
            st.download_button("Download annotated PDF", data=Path(pdf_path).read_bytes(),
                               file_name=Path(pdf_path).name, mime="application/pdf",
                               key=f"{run_id}_download_annotated", on_click="ignore")
            for page_png in result.get("annotated_page_paths", []):
                st.image(page_png, caption=Path(page_png).stem)
        else:
            st.info("Parse the document to create an annotated PDF.")

if tab_html.open:
    with tab_html:
        if current_parse:
            rendered_html = parse_to_html(current_parse)
            st.download_button("Download HTML", data=rendered_html, file_name=f"{doc_sha}.html",
                               mime="text/html", key=f"{run_id}_download_html", on_click="ignore")
            st.iframe(rendered_html, height=800)
        else:
            st.info("Parse the document to create HTML.")

if tab_json.open:
    with tab_json:
        if current_parse:
            json_text = current_parse.model_dump_json(indent=2)
            st.download_button("Download JSON", data=json_text, file_name=f"{doc_sha}.json",
                               mime="application/json", key=f"{run_id}_download_json", on_click="ignore")
            copy_buttons(data={"label": "Copy JSON", "text": json_text},
                         key=f"{run_id}_copy_json", height="content")
            st.json(current_parse.model_dump())
        else:
            st.info("Parse the document to create grounded layout JSON.")
