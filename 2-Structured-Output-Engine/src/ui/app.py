"""Streamlit UI for the Structured Output Engine — wraps engine.pipeline.Pipeline,
which already does the real work (retry, repair, fallback). Run via
`run.cmd` or `python -m streamlit run src/ui/app.py` from the project root.
"""

from __future__ import annotations

import json
import logging
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st
from pydantic import BaseModel

from engine.file_input import OcrError, is_text_file, load_text_from_file
from engine.pipeline import Pipeline, PipelineFailure
from eval import load_cases, run_eval
from providers import AgnesProvider, GeminiProvider, OllamaProvider, OpenAICompatibleProvider
from providers.base import Provider, ProviderError
from providers.ollama_provider import ALLOWED_MODELS as OLLAMA_ALLOWED_MODELS
from schemas import SchemaConversionError, model_from_json_schema, registry

EVAL_CASES_PATH = Path(__file__).resolve().parent.parent.parent / "tests" / "eval" / "cases.jsonl"
PASTE_SCHEMA_OPTION = "Paste JSON Schema"

PROVIDER_FACTORIES: dict[str, type[Provider]] = {
    "ollama": OllamaProvider,
    "agnes": AgnesProvider,
    "openai": OpenAICompatibleProvider,
    "gemini": GeminiProvider,
}
# Non-Ollama model lists are fixed (NOTES.md); Ollama's is dynamic (below).
KNOWN_MODELS = {
    "agnes": ["agnes-2.5-flash"],
    "openai": ["gpt-5.6-luna", "gpt-5.6-terra"],
    "gemini": ["gemini-3.5-flash-lite", "gemini-3.7-flash"],
}


@st.cache_data(ttl=30)
def ollama_model_options() -> list[str]:
    """Installed models ∩ allowlist, via OllamaProvider.installed_models() —
    falls back to the full local allowlist if Ollama isn't reachable, so the
    dropdown is never empty."""
    try:
        installed = sorted(OllamaProvider("granite4.1:3b").installed_models())
    except Exception:
        installed = []
    return installed or sorted(OLLAMA_ALLOWED_MODELS)

_PIPELINE_LOGGER = logging.getLogger("engine.pipeline")
_PIPELINE_LOGGER.setLevel(logging.INFO)


class _AttemptCollector(logging.Handler):
    """Captures Pipeline's existing per-attempt logging (see engine/pipeline.py)
    as structured rows for the timeline table, without changing Pipeline at all."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[dict] = []

    def emit(self, record: logging.LogRecord) -> None:
        if not isinstance(record.args, tuple) or len(record.args) != 8:
            return
        attempt, stage, provider, model, ok, latency_ms, error_types, snippet = record.args
        self.rows.append(
            {
                "attempt": attempt,
                "stage": stage,
                "provider": provider,
                "model": model,
                "ok": ok,
                "latency_ms": round(latency_ms, 1),
                "errors": ", ".join(error_types) if error_types else "",
                "raw": snippet,
            }
        )


def run_pipeline_with_timeline(pipeline: Pipeline, text: str, schema: type[BaseModel]):
    """Pipeline.run(), plus the attempt timeline. Never raises PipelineFailure
    — a fallback="raise" result comes back as exc.result, same as any other
    StructuredResult, so the UI only ever has one shape to render."""
    _PIPELINE_LOGGER.handlers = [h for h in _PIPELINE_LOGGER.handlers if not isinstance(h, _AttemptCollector)]
    collector = _AttemptCollector()
    _PIPELINE_LOGGER.addHandler(collector)
    try:
        result = pipeline.run(text, schema)
    except PipelineFailure as exc:
        result = exc.result
    finally:
        _PIPELINE_LOGGER.removeHandler(collector)
    return result, collector.rows


def resolve_selected_schema(schema_choice: str, pasted_schema_text: str | None):
    """Returns (schema_cls, error_message)."""
    if schema_choice != PASTE_SCHEMA_OPTION:
        return registry.get(schema_choice), None
    if not pasted_schema_text or not pasted_schema_text.strip():
        return None, "Paste a JSON Schema below to use it."
    try:
        schema_dict = json.loads(pasted_schema_text)
    except json.JSONDecodeError as exc:
        return None, f"Invalid JSON: {exc}"
    try:
        return model_from_json_schema(schema_dict), None
    except SchemaConversionError as exc:
        return None, str(exc)


def render_result(result, timeline: list[dict]) -> None:
    if result.ok:
        st.success(f"Valid after {result.attempts} attempt(s).")
    else:
        st.error(f"Not valid after {result.attempts} attempt(s).")

    data = result.data.model_dump(mode="json") if isinstance(result.data, BaseModel) else result.data
    if data is not None:
        st.caption("Data" if result.ok else "Partial data")
        st.json(data)

    if result.errors:
        st.subheader("Validation errors")
        st.dataframe(
            pd.DataFrame(
                [{"loc": ".".join(map(str, e.loc)) or "(root)", "msg": e.msg, "type": e.type} for e in result.errors]
            ),
            hide_index=True,
        )

    if timeline:
        st.subheader("Attempt timeline")
        st.dataframe(pd.DataFrame(timeline), hide_index=True, column_config={"raw": None})

    with st.expander("Raw model text (last attempt)"):
        st.code(result.raw_text or "(empty)", language="json")


st.set_page_config(page_title="Structured Output Engine", layout="wide")
st.title("Structured output engine")
st.caption("Text (or an image/scanned PDF) + a schema → a validated instance, or a typed failure. Never raw text.")

with st.sidebar:
    st.header("Settings")
    provider_name = st.selectbox("Provider", sorted(PROVIDER_FACTORIES), key="ui_provider")
    model_options = ollama_model_options() if provider_name == "ollama" else KNOWN_MODELS[provider_name]
    model = st.selectbox("Model", model_options, key=f"ui_model_{provider_name}")
    repair_model = st.text_input("Repair model", value="qwen3.5:0.8b", key="ui_repair_model")
    pin_provider = st.checkbox(
        "Repair with the same provider/model", key="ui_pin_provider",
        help="Off (default): repair always switches to the repair model above via local Ollama.",
    )
    max_attempts = st.number_input("Max attempts", min_value=1, max_value=10, value=3, key="ui_max_attempts")
    fallback = st.selectbox("Fallback mode", ["partial", "empty", "raise"], key="ui_fallback")

    st.divider()
    schema_choice = st.selectbox("Schema", [*registry.names(), PASTE_SCHEMA_OPTION], key="ui_schema_choice")
    pasted_schema_text = None
    if schema_choice == PASTE_SCHEMA_OPTION:
        pasted_schema_text = st.text_area(
            "JSON Schema", height=180, key="ui_pasted_schema",
            placeholder='{"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}',
        )

schema_cls, schema_error = resolve_selected_schema(schema_choice, pasted_schema_text)

tab_run, tab_schema, tab_eval = st.tabs(["Run", "Schema", "Eval"])

with tab_run:
    text_input = st.text_area("Paste text", height=180, key="ui_text_input")
    uploaded = st.file_uploader(
        "...or upload a file (text/md/json read directly; images/PDF are OCR'd first)",
        type=["txt", "md", "json", "png", "jpg", "jpeg", "bmp", "tif", "tiff", "webp", "pdf"],
        key="ui_uploaded_file",
    )

    if schema_error:
        st.warning(schema_error)
    run_clicked = st.button("Run", type="primary", disabled=schema_cls is None, key="ui_run_button")

    if run_clicked:
        text: str | None = None
        if uploaded is not None:
            suffix = Path(uploaded.name).suffix or ".txt"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(uploaded.getvalue())
                tmp_path = Path(tmp.name)
            try:
                with st.spinner("Reading file..." if is_text_file(tmp_path) else "Running OCR..."):
                    text = load_text_from_file(tmp_path)
            except OcrError as exc:
                st.error(f"OCR failed [{exc.code}]: {exc.message}")
            finally:
                tmp_path.unlink(missing_ok=True)
        else:
            text = text_input

        if text is not None and not text.strip():
            st.warning("Nothing to run — paste text or upload a file.")
            text = None

        if text is not None:
            try:
                provider = PROVIDER_FACTORIES[provider_name](model)
            except ProviderError as exc:
                st.error(f"Provider error [{exc.code}]: {exc.message}")
            else:
                pipeline = Pipeline(
                    provider,
                    model,
                    repair_model=repair_model,
                    pin_provider=pin_provider,
                    max_attempts=int(max_attempts),
                    fallback=fallback,
                )
                with st.spinner("Running..."):
                    result, timeline = run_pipeline_with_timeline(pipeline, text, schema_cls)
                st.session_state["ui_result"] = result
                st.session_state["ui_timeline"] = timeline

    st.divider()
    if st.session_state.get("ui_result") is not None:
        render_result(st.session_state["ui_result"], st.session_state.get("ui_timeline", []))

with tab_schema:
    if schema_error:
        st.warning(schema_error)
    elif schema_cls is not None:
        st.subheader(schema_choice)
        st.json(schema_cls.model_json_schema())
        st.subheader("Example")
        if schema_choice in registry.names():
            st.json(registry.example(schema_choice).model_dump(mode="json"))
        else:
            st.caption("No canonical example for a pasted schema.")

with tab_eval:
    cases = load_cases(EVAL_CASES_PATH) if EVAL_CASES_PATH.exists() else []
    if not cases:
        st.warning(f"No eval cases found at `{EVAL_CASES_PATH}`.")
    else:
        st.caption(f"{len(cases)} cases across {len({c['schema'] for c in cases})} schemas — {EVAL_CASES_PATH}")

    if st.button("Run eval", disabled=not cases, key="ui_run_eval_button"):
        try:
            eval_provider = PROVIDER_FACTORIES[provider_name](model)
        except ProviderError as exc:
            st.error(f"Provider error [{exc.code}]: {exc.message}")
        else:
            eval_pipeline = Pipeline(
                eval_provider,
                model,
                repair_model=repair_model,
                pin_provider=pin_provider,
                max_attempts=int(max_attempts),
                fallback=fallback,
            )
            with st.spinner(f"Running {len(cases)} cases..."):
                st.session_state["ui_eval_summary"] = run_eval(eval_pipeline, cases)

    summary = st.session_state.get("ui_eval_summary")
    if summary is not None:
        cols = st.columns(4)
        cols[0].metric("Valid rate", f"{summary.valid_rate:.0%}")
        cols[1].metric("Repair rate", f"{summary.repair_rate:.0%}")
        cols[2].metric("Mean attempts", f"{summary.mean_attempts:.2f}")
        cols[3].metric("Mean latency", f"{summary.mean_latency_ms:.0f} ms")
        st.caption(f"Failure rate: {summary.failure_rate:.0%}")

        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "id": r.case_id,
                        "schema": r.schema,
                        "category": r.category,
                        "ok": r.ok,
                        "attempts": r.attempts,
                        "latency_ms": round(r.latency_ms, 1) if r.latency_ms is not None else None,
                        "errors": ", ".join(r.error_types),
                    }
                    for r in summary.results
                ]
            ),
            hide_index=True,
        )
