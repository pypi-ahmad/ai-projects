"""Streamlit tool runner: browse registered tools, make a manual call
against one via a form generated from its schema, or chat with the loop
and see the last run's tool-call trace (calls, errors, retries).

Talks to the FastAPI surface (src/tools/api.py) over HTTP at
API_BASE_URL -- run both via run.cmd, or `streamlit run src/tools/ui.py`
with the API already running separately.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import requests
import streamlit as st

API_BASE_URL = "http://127.0.0.1:8765"

st.set_page_config(page_title="Tool-Calling Framework", page_icon=":material/build:", layout="wide")


def _get_tools() -> list[dict[str, Any]]:
    resp = requests.get(f"{API_BASE_URL}/v1/tools", timeout=10)
    resp.raise_for_status()
    return resp.json()


def _post_call(name: str, args: dict[str, Any], run_id: str) -> dict[str, Any]:
    resp = requests.post(
        f"{API_BASE_URL}/v1/call", json={"name": name, "args": args, "run_id": run_id}, timeout=30
    )
    resp.raise_for_status()
    return resp.json()


def _post_loop(
    messages: list[dict[str, Any]], run_id: str, *, provider: str, max_tool_iters: int
) -> dict[str, Any]:
    resp = requests.post(
        f"{API_BASE_URL}/v1/loop",
        json={
            "messages": messages,
            "run_id": run_id,
            "provider": provider,
            "max_tool_iters": max_tool_iters,
        },
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()


def _render_args_form(tool_name: str, schema: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """One input per schema property. Returns (typed_values, raw_json_fields_to_parse_on_submit)."""
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    values: dict[str, Any] = {}
    json_raw: dict[str, str] = {}

    for key, prop in properties.items():
        is_required = key in required
        label = f"{key} *" if is_required else key
        widget_key = f"arg_{tool_name}_{key}"
        prop_type = prop.get("type")
        if prop_type is None and "anyOf" in prop:
            non_null = [s for s in prop["anyOf"] if s.get("type") != "null"]
            prop_type = non_null[0].get("type") if non_null else None

        if prop_type == "string":
            value = st.text_input(label, key=widget_key)
            if value or is_required:
                values[key] = value
        elif prop_type == "integer":
            values[key] = int(st.number_input(label, step=1, key=widget_key))
        elif prop_type == "number":
            values[key] = st.number_input(label, key=widget_key)
        elif prop_type == "boolean":
            values[key] = st.checkbox(label, key=widget_key)
        else:
            # object / array / Any (no declared type) -- raw JSON, parsed on submit
            json_raw[key] = st.text_area(f"{label} (JSON)", key=widget_key)

    return values, json_raw


def _extract_trace(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """{tool, args, ok, error, attempts, duration_ms} per tool call in a loop result."""
    trace: list[dict[str, Any]] = []
    pending_args: dict[str, Any] | None = None
    for msg in messages:
        if msg.get("role") == "assistant" and msg.get("tool_call"):
            pending_args = msg["tool_call"]["args"]
        elif msg.get("role") == "tool":
            result = json.loads(msg["content"])
            trace.append(
                {
                    "tool": result["tool"],
                    "args": pending_args,
                    "ok": result["ok"],
                    "error": result["error"]["code"] if result["error"] else None,
                    "attempts": result.get("attempts", 1),
                    "duration_ms": round(result["duration_ms"], 1),
                }
            )
            pending_args = None
    return trace


# st.session_state is per-browser-session (Streamlit re-runs this whole
# script on every interaction; these three values are what survives a
# rerun). run_id is generated once per session and threaded through every
# /v1/call and /v1/loop request so a browser tab's tool calls land in one
# data/sandbox/<run_id>/ directory.
if "run_id" not in st.session_state:
    st.session_state.run_id = uuid.uuid4().hex
if "chat_messages" not in st.session_state:
    st.session_state.chat_messages = []
if "last_trace" not in st.session_state:
    st.session_state.last_trace = []

st.title("Tool-calling framework")
st.caption(f"run_id: `{st.session_state.run_id}`")

try:
    tools = _get_tools()
except requests.exceptions.RequestException as exc:
    st.error(f"Can't reach the API at {API_BASE_URL}: {exc}")
    st.stop()

with st.sidebar:
    st.header("Tools")
    for tool in tools:
        with st.expander(tool["name"]):
            st.write(tool["description"])
            st.json(tool["parameters"])

    st.divider()
    st.header("Last run trace")
    if st.session_state.last_trace:
        st.dataframe(st.session_state.last_trace, width="stretch")
    else:
        st.caption("No run yet.")

tab_chat, tab_manual = st.tabs(["Chat", "Manual call"])

with tab_manual:
    tool_names = [t["name"] for t in tools]
    selected = st.selectbox("Tool", tool_names)
    schema = next(t["parameters"] for t in tools if t["name"] == selected)

    with st.form("manual_call_form"):
        values, json_raw = _render_args_form(selected, schema)
        submitted = st.form_submit_button("Call")

    if submitted:
        try:
            for key, raw in json_raw.items():
                if raw.strip():
                    values[key] = json.loads(raw)
        except json.JSONDecodeError as exc:
            st.error(f"Invalid JSON: {exc}")
        else:
            result = _post_call(selected, values, st.session_state.run_id)
            if result["ok"]:
                st.success("Call succeeded")
            else:
                st.error(f"{result['error']['code']}: {result['error']['message']}")
            st.json(result)

with tab_chat:
    provider = st.selectbox("Provider", ["ollama", "openai", "agnes", "gemini"], key="provider_select")

    for msg in st.session_state.chat_messages:
        # An assistant message with a tool_call is an internal turn (its
        # content is often None -- the model said nothing, just called a
        # tool); only its *final* text reply belongs in the chat display.
        is_displayable = msg["role"] == "user" or (
            msg["role"] == "assistant" and not msg.get("tool_call")
        )
        if is_displayable:
            with st.chat_message(msg["role"]):
                st.write(msg["content"])

    prompt = st.chat_input("Ask something -- it can use the tools above")
    if prompt:
        st.session_state.chat_messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.write(prompt)

        with st.chat_message("assistant"):
            result = None
            with st.spinner("Thinking..."):
                try:
                    result = _post_loop(
                        st.session_state.chat_messages,
                        st.session_state.run_id,
                        provider=provider,
                        max_tool_iters=4,
                    )
                except requests.exceptions.RequestException as exc:
                    st.error(f"Loop call failed: {exc}")

            if result is not None:
                if result["status"] == "FINAL":
                    st.write(result["text"])
                else:
                    st.warning(
                        f"Stopped: {result['status']} after {result['iterations']} tool iterations"
                    )
                st.session_state.chat_messages = result["messages"]
                st.session_state.last_trace = _extract_trace(result["messages"])
                st.rerun()  # so the sidebar trace (rendered earlier in the script) reflects this turn
