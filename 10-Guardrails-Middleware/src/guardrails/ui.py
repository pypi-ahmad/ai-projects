"""Streamlit playground — manual test console for `Guard`.

Run with `streamlit run src/guardrails/ui.py` (or `run.cmd`). Text typed here
never leaves this process except to a classifier provider you explicitly
enable below.

This is the last module in the walk -- see `pipeline.py` to go back to the
run loop these widgets are driving.
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, cast

import streamlit as st

from guardrails import Guard
from guardrails.pii import PiiDetector
from guardrails.providers import (
    DEFAULT_CLASSIFIER_CONFIG,
    EmbeddingSimilarityDetector,
    LlmClassifierDetector,
)
from guardrails.rules import InputRulesDetector, OutputRulesDetector

if TYPE_CHECKING:
    from guardrails.policies import Policy

st.set_page_config(page_title="Guardrails playground", page_icon=":material/shield:")
st.title("Guardrails playground")
st.caption("Rules run always. Classifiers only run if you turn them on below.")

direction = cast(
    "str",
    st.segmented_control("Direction", options=["input", "output"], default="input") or "input",
)
policy = cast(
    "Policy",
    st.segmented_control("Policy", options=["strict", "standard", "observe"], default="standard")
    or "standard",
)

with st.container(border=True):
    st.caption("Optional LLM classifier (Ollama) — off by default, needs a provider running")
    use_llm_classifier = st.toggle("Use LLM classifier", value=False)
    use_embedding_lane = st.toggle("Use embedding similarity lane", value=False)

text = st.text_area("Text to check", height=150, placeholder="Paste a prompt or a model reply...")
run_check = st.button("Check", type="primary")

if run_check:
    classifier_config = copy.deepcopy(DEFAULT_CLASSIFIER_CONFIG)
    classifier_config["use_llm_classifier"] = use_llm_classifier
    classifier_config["embedding_lane"]["enabled"] = use_embedding_lane

    guard = Guard(
        input_detectors=[
            PiiDetector(),
            InputRulesDetector(),
            LlmClassifierDetector(config=classifier_config),
            EmbeddingSimilarityDetector(config=classifier_config),
        ],
        output_detectors=[PiiDetector(), OutputRulesDetector()],
        policy=policy,
    )

    with st.spinner("Checking..."):
        decision = guard.check_input(text) if direction == "input" else guard.check_output(text)

    action_display = {
        "allow": ("Allow", st.success),
        "transform": ("Transform", st.warning),
        "block": ("Block", st.error),
    }
    label, renderer = action_display[decision.action]
    renderer(f"**{label}** — {decision.latency_ms:.1f} ms")

    st.subheader("Findings")
    if decision.findings:
        rows = [
            {
                "detector": f.detector_id,
                "severity": f.severity,
                "spans": ", ".join(s.type for s in f.spans) or "-",
                "message": f.message,
            }
            for f in decision.findings
        ]
        st.dataframe(rows, width="stretch")
    else:
        st.caption("No findings.")

    st.subheader("Output text")
    st.text_area("text_out", value=decision.text_out, height=150, label_visibility="collapsed")
