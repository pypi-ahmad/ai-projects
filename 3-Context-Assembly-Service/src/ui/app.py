"""
Streamlit UI for the Context Assembly Service.

Trust note: block text entered in the "Add block" form (and any pasted fixture
JSON) is packed verbatim into the outgoing chat messages with no sanitization —
this UI does not defend against prompt injection in user-supplied block text.
"""
import json
import sys
import uuid
from pathlib import Path

# Lets `streamlit run src/ui/app.py` resolve `from src....` imports regardless
# of the cwd streamlit was launched from, without requiring a pip install.
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from src.blocks.models import ContextBlock, ContextRequest
from src.blocks.tokenizer import TokenCounter
from src.budget.allocator import allocate
from src.budget.policy import load_policy
from src.assembly.packer import pack
from src.compress.compressor import run_compress_jobs

_COUNTER  = TokenCounter()
_FIXTURE  = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "sample_request.json"
_POLICIES = ["balanced", "docs_heavy", "tools_heavy", "memory_heavy"]
_FAMILIES = ["memory", "docs", "tools", "system"]
_MODELS   = ["granite4.1:3b", "qwen3.5:2b", "qwen3.5:0.8b", "custom"]

st.set_page_config(page_title="Context Assembly", layout="wide", page_icon="📦")

# ── session state ─────────────────────────────────────────────────────────────
if "blocks"       not in st.session_state: st.session_state.blocks       = []
if "user_message" not in st.session_state: st.session_state.user_message = ""
if "result"       not in st.session_state: st.session_state.result       = None
if "plan"         not in st.session_state: st.session_state.plan         = None

# ── sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Settings")

    model_choice = st.selectbox("Target model", _MODELS)
    if model_choice == "custom":
        ctx_window  = st.number_input("Context window (tokens)", 100, 2_000_000, 4096, 512)
        model_name  = None
    else:
        ctx_window  = None
        model_name  = model_choice

    policy_name = st.selectbox("Policy", _POLICIES)

    compress_mode = st.selectbox(
        "Compress provider",
        ["off", "auto"],
        help="'auto' uses the provider chain (Ollama → Agnes → OpenAI-compat → Gemini). "
             "'off' skips compression — compress-eligible blocks are excluded from output.",
    )

    reserve_output = st.number_input(
        "Reserve output tokens", 0, 100_000, 512, 64,
        help="Tokens reserved for model generation; never packed into input.",
    )

# ── helpers ───────────────────────────────────────────────────────────────────
def _load_fixture() -> None:
    data = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    st.session_state.blocks = [
        {
            "id":           b["id"],
            "family":       b["family"],
            "text":         b["text"],
            "priority":     b.get("priority", 50),
            "droppable":    b.get("droppable", True),
            "compressible": b.get("compressible", False),
        }
        for b in data.get("blocks", [])
    ]
    st.session_state.user_message = data.get("user_message", "")


def _build_request() -> ContextRequest:
    blocks = [
        ContextBlock(
            id=b["id"],
            family=b["family"],
            text=b["text"],
            priority=b["priority"],
            droppable=b["droppable"],
            compressible=b["compressible"],
        )
        for b in st.session_state.blocks
    ]
    return ContextRequest(
        blocks=blocks,
        user_message=st.session_state.user_message or "(no message)",
        model_name=model_name,
        context_window=int(ctx_window) if ctx_window else None,
        reserve_output_tokens=int(reserve_output) if reserve_output else None,
        policy=policy_name,
    )


def _run_assembly() -> None:
    try:
        req    = _build_request()
        policy = load_policy(policy_name)
        plan   = allocate(req, policy)
        if compress_mode == "auto" and plan.compress_jobs:
            plan = run_compress_jobs(plan, unload_after=True)
        result = pack(req, plan, policy)
        st.session_state.result = result
        st.session_state.plan   = plan
    except Exception as exc:
        # Deliberately broad: any failure (bad fixture, policy error, provider
        # exception) surfaces as a message instead of crashing the app — but that
        # also means real bugs here show only this string, not a traceback.
        st.error(f"Assembly error: {exc}")

# ── header row ────────────────────────────────────────────────────────────────
st.title("📦 Context Assembly Service")
hc1, hc2, hc3, _ = st.columns([2, 2, 2, 4])
if hc1.button("📂 Load sample"):
    _load_fixture()
    st.session_state.result = None
    st.rerun()
if hc2.button("🗑 Clear"):
    st.session_state.blocks = []
    st.session_state.result = None
    st.rerun()
if hc3.button("▶ Assemble", type="primary"):
    _run_assembly()

# ── block editor ──────────────────────────────────────────────────────────────
st.divider()
st.subheader("Blocks")

st.session_state.user_message = st.text_input(
    "User message", value=st.session_state.user_message,
    placeholder="What question should the model answer?",
)

with st.expander("➕ Add block", expanded=len(st.session_state.blocks) == 0):
    with st.form("add_block", clear_on_submit=True):
        f1, f2, f3, f4 = st.columns([2, 1, 1, 1])
        fam  = f1.selectbox("Family", _FAMILIES, label_visibility="collapsed")
        pri  = f2.number_input("Priority", 0, 100, 50, label_visibility="collapsed")
        drop = f3.checkbox("Droppable", value=True)
        comp = f4.checkbox("Compressible", value=False)
        text = st.text_area("Block text", height=90, placeholder="Paste your block content here…")
        if st.form_submit_button("Add block") and text.strip():
            st.session_state.blocks.append({
                "id":           uuid.uuid4().hex[:8],
                "family":       fam,
                "text":         text.strip(),
                "priority":     int(pri),
                "droppable":    drop,
                "compressible": comp,
            })
            st.rerun()

if st.session_state.blocks:
    for i, b in enumerate(list(st.session_state.blocks)):
        c_fam, c_pri, c_flags, c_text, c_tok, c_del = st.columns([1, 1, 1, 5, 1, 1])
        c_fam.caption(f"**{b['family']}**")
        c_pri.caption(f"p={b['priority']}")
        flags = ("C" if b["compressible"] else "") + ("" if b["droppable"] else "K")
        c_flags.caption(flags or "—")
        c_text.caption(b["text"][:90] + ("…" if len(b["text"]) > 90 else ""))
        c_tok.caption(f"{_COUNTER.count(b['text'])} tok")
        if c_del.button("×", key=f"del_{i}_{b['id']}"):
            st.session_state.blocks.pop(i)
            st.rerun()
else:
    st.info("No blocks yet. Click **Load sample** or add one above.")

# ── results ───────────────────────────────────────────────────────────────────
if st.session_state.result is not None:
    result = st.session_state.result
    r      = result.report

    st.divider()
    st.subheader("Results")

    # Summary metrics
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Window",   r.context_window)
    m2.metric("Reserves", r.reserve_tokens)
    m3.metric("Usable",   r.usable)
    m4.metric("Used",     r.token_total - r.reserve_tokens)
    m5.metric("Leftover", r.leftover, delta=f"{r.leftover/r.usable*100:.0f}%" if r.usable else "")

    # Family token bars
    st.write("")
    st.caption("Token usage per family — bar = used / cap")
    fb1, fb2, fb3 = st.columns(3)
    for col, (fam, stat) in zip([fb1, fb2, fb3], r.per_family.items()):
        pct = min(stat.used / stat.cap, 1.0) if stat.cap > 0 else 0.0
        col.write(f"**{fam}** {stat.used} / {stat.cap}")
        col.progress(pct)

    # Packed messages
    st.write("")
    with st.expander("📨 Packed messages", expanded=True):
        for msg in result.messages:
            st.markdown(f"`{msg['role']}`")
            st.code(msg["content"], language=None, wrap_lines=True)

    # Dropped
    if r.dropped:
        st.subheader(f"Dropped ({len(r.dropped)})")
        st.dataframe(r.dropped, use_container_width=True)

    # Compress
    if r.compress_ids:
        status = "skipped (compress=off)" if compress_mode == "off" else "run"
        st.subheader(f"Compress jobs ({len(r.compress_ids)}) — {status}")
        st.dataframe([{"id": cid} for cid in r.compress_ids], use_container_width=True)

    # Export
    st.divider()
    export_payload = json.dumps(
        {"messages": result.messages, "packed_text": result.packed_text, "report": r.as_dict()},
        indent=2, ensure_ascii=False,
    )
    st.download_button(
        "⬇ Export pack.json",
        data=export_payload.encode("utf-8"),
        file_name="pack.json",
        mime="application/json",
    )
