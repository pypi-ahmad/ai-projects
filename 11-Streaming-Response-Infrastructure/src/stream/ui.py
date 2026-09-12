"""Streamlit consumer of the SSE endpoint.

A consumer, not the source of truth -- `stream.api` (FastAPI) owns the
actual stream plumbing. Streamlit's rerun model doesn't drive a browser
`EventSource` well from Python, so this calls the HTTP API with httpx2's
synchronous streaming client from inside a generator, and `st.write_stream`
renders it token-by-token -- Streamlit's own recommended shape for any
LLM-style stream (see the developing-with-streamlit skill's chat-ui
reference). The `Last-Event-ID` reconnect demo lives in `src/ui/client.html`
instead, where a real `EventSource` makes it a one-line browser feature.

Run: `uv run streamlit run src/stream/ui.py` (port/theme come from
`.streamlit/config.toml`, not a flag) with `stream.api` already serving on
127.0.0.1:8000 (see run.cmd).

Must not become a second source of truth for the SSE/session protocol --
if the parsing below drifts from `stream.sse`/`stream.session`, fix the
mismatch, don't fork it further. Next: `src/ui/client.html` for the other
consumer of the same API.
"""

import time
from collections.abc import Iterator

import httpx2 as httpx
import streamlit as st

from stream.config import MODEL_ALLOWLIST, PROVIDERS

API_BASE = "http://127.0.0.1:8000"

st.set_page_config(page_title="Streaming response infrastructure", page_icon="⚡")
st.title("Streaming response infrastructure")
st.caption("The product is the stream plumbing, not a chatbot -- this is a thin consumer of it.")

verified_providers = [name for name, status in PROVIDERS.items() if status.enabled]
provider = st.selectbox("Provider", ["fake", *verified_providers])
model = st.selectbox("Model", MODEL_ALLOWLIST[provider]) if provider != "fake" else "fake"
prompt = st.text_area("Prompt", "Reply with exactly one short sentence.")

if st.button("Start stream", icon=":material/play_arrow:", width="stretch"):
    with httpx.Client(timeout=10.0) as client:
        start = client.post(
            f"{API_BASE}/v1/stream/start",
            json={
                "provider": provider,
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
            },
        )

    if start.status_code != 200:
        detail = start.json().get("detail", start.text)
        st.error(f"Start failed ({start.status_code}): {detail}")
    else:
        body = start.json()
        session_id = body["session_id"]
        sse_url = f"{API_BASE}{body['sse_url']}"
        first_token_ms: list[float] = []
        stream_errors: list[str] = []

        def tokens() -> Iterator[str]:
            # Minimal SSE line parser, not a general one: assumes one
            # data: line per event (true for stream.sse.sse_format's
            # token/error/done events) and ignores retry:/comment lines by
            # simply never matching their prefix. Good enough for this
            # server's own wire format, not a spec-complete EventSource.
            connect_at = time.monotonic()
            with httpx.Client(timeout=None) as client, client.stream("GET", sse_url) as resp:
                event_type = None
                for line in resp.iter_lines():
                    if line.startswith("event:"):
                        event_type = line.removeprefix("event:").strip()
                    elif line.startswith("data:"):
                        data = line.removeprefix("data:").removeprefix(" ")
                        if event_type == "token" and data:
                            if not first_token_ms:
                                first_token_ms.append((time.monotonic() - connect_at) * 1000)
                            yield data
                        elif event_type == "error" and data:
                            stream_errors.append(data)
                        if event_type in ("done", "error"):
                            break

        with st.container(border=True):
            st.write_stream(tokens())

        if stream_errors:
            st.error(f"Stream error: {stream_errors[0]}")

        if first_token_ms:
            st.metric("TTFT (client, this connection)", f"{first_token_ms[0]:.1f} ms")

        with httpx.Client(timeout=10.0) as client:
            metrics = client.get(f"{API_BASE}/v1/metrics/{session_id}").json()
        st.caption(
            f"Server metrics -- ttft_ms={metrics.get('ttft_ms')}, "
            f"tokens={metrics.get('tokens')}, done_reason={metrics.get('done_reason')}"
        )
