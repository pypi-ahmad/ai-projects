"""Streamlit trace viewer + alert inbox. Talks to the FastAPI backend over
HTTP (obs.ui.api_client) - does not import obs.export/obs.alerts directly.

Run via run.cmd, or directly:
    uv run streamlit run src/obs/ui/app.py --server.port 7017
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import altair as alt
import pandas as pd
import requests
import streamlit as st

from obs.ui import api_client

st.set_page_config(page_title="LLM Observability Stack", layout="wide")
st.title("LLM Observability Stack")

if os.environ.get("OBS_STORE_PROMPTS", "").lower() == "true":
    st.warning(
        "`OBS_STORE_PROMPTS=true` — full prompt/response text is being stored, "
        "not just a hash + 120-char preview. See docs/PRIVACY.md.",
        icon=":material/privacy_tip:",
    )

# --- Demo complete (Ollama) ---
with st.container(border=True):
    st.subheader("Demo: send a traced Ollama call")
    with st.form("demo_complete_form"):
        demo_model = st.text_input("Model", value="qwen3.5:0.8b")
        demo_prompt = st.text_area("Prompt", value="Say hello in one short sentence.")
        submitted = st.form_submit_button("Send")
    if submitted:
        try:
            result = api_client.demo_complete(
                [{"role": "user", "content": demo_prompt}], provider="ollama", model=demo_model
            )
        except requests.exceptions.RequestException as exc:
            st.error(f"Request failed: {exc}")
        else:
            st.success(result["text"])
            st.caption(
                f"trace_id `{result['trace_id']}` · in_tokens {result['in_tokens']} · "
                f"out_tokens {result['out_tokens']} · ttft_ms {result['ttft_ms']}"
            )

st.divider()

# --- Alert inbox ---
st.subheader("Alerts")
if st.button("Refresh alerts", icon=":material/refresh:"):
    st.rerun()

try:
    alerts = api_client.list_alerts()
except requests.exceptions.RequestException as exc:
    st.error(f"Could not load alerts: {exc}")
    alerts = []

if not alerts:
    st.caption("No alerts.")
else:
    for alert in alerts:
        with st.container(border=True):
            info_col, ack_col = st.columns([5, 1])
            with info_col:
                st.markdown(
                    f"**{alert['rule']}** ({alert['severity']}) — route `{alert['route']}` "
                    f"model `{alert['model']}` — value {alert['value']:.4f} vs. "
                    f"threshold {alert['threshold']:.4f} — window `{alert['window']}`"
                )
                st.caption(f"trace_ids: {', '.join(alert['trace_ids']) or '(none)'}")
            with ack_col:
                if alert["acked"]:
                    st.caption("Acked")
                elif st.button("Ack", key=f"ack-{alert['id']}"):
                    api_client.ack_alert(alert["id"])
                    st.rerun()

st.divider()

# --- Trace filters + list ---
st.subheader("Traces")

filter_cols = st.columns(3)
with filter_cols[0]:
    since_hours = st.number_input("Since (hours ago, 0 = no limit)", min_value=0, value=24, step=1)
with filter_cols[1]:
    model_filter = st.text_input("Model contains", value="")
with filter_cols[2]:
    status_filter = st.segmented_control("Status", options=["any", "ok", "error"], default="any")

since = (datetime.now(UTC) - timedelta(hours=since_hours)).isoformat() if since_hours > 0 else None
status = None if status_filter in (None, "any") else status_filter

try:
    rows = api_client.list_traces(model=model_filter or None, since=since, status=status)
except requests.exceptions.RequestException as exc:
    st.error(f"Could not load traces: {exc}")
    rows = []

if not rows:
    st.caption("No traces match these filters.")
else:
    df = pd.DataFrame(rows)
    display_cols = [
        c
        for c in [
            "ts",
            "trace_id",
            "name",
            "model",
            "status",
            "latency_ms",
            "in_tokens",
            "out_tokens",
            "cost_est",
            "pricing",
        ]
        if c in df.columns
    ]
    st.dataframe(df[display_cols], width="stretch", hide_index=True)

    trace_ids = df["trace_id"].unique().tolist()
    selected_trace_id = st.selectbox("View trace waterfall", options=trace_ids)

    if selected_trace_id:
        trace = api_client.get_trace(selected_trace_id)
        if trace and trace["spans"]:
            spans = trace["spans"]
            # start_ns/end_ns are a monotonic clock (see trace/models.py) -
            # no fixed epoch, so only differences within this one trace are
            # meaningful. Offsetting every span by this trace's own
            # earliest start_ns is what makes the bars comparable.
            t0 = min(s["start_ns"] for s in spans)
            waterfall_rows = [
                {
                    "span": f"{s['name']} ({s['ctx']['span_id'][:8]})",
                    "start_ms": (s["start_ns"] - t0) / 1_000_000,
                    "end_ms": (s["end_ns"] - t0) / 1_000_000
                    if s["end_ns"] is not None
                    else (s["start_ns"] - t0) / 1_000_000,
                    "status": s["status"],
                }
                for s in spans
            ]
            wf_df = pd.DataFrame(waterfall_rows)
            chart = (
                alt.Chart(wf_df)
                .mark_bar()
                .encode(  # ty: ignore[unresolved-attribute]  # Altair's fluent API is dynamic.
                    x=alt.X("start_ms:Q", title="ms from trace start"),
                    x2="end_ms:Q",
                    y=alt.Y("span:N", sort=None, title=None),
                    color=alt.Color(
                        "status:N",
                        scale=alt.Scale(domain=["ok", "error"], range=["#4C9A2A", "#D64545"]),
                    ),
                )
            )
            st.altair_chart(chart, width="stretch")
