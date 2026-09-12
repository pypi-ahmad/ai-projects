"""Streamlit front-end for the Model Routing Gateway.

Streamlit re-runs this entire module top-to-bottom on every widget
interaction (button click, checkbox toggle, etc.) — there is no persistent
app object between reruns. State that must survive a rerun goes through
st.cache_resource/st.cache_data (see _load_configs below) or st.session_state
(not used here); everything else is recomputed each time.

No authentication: any request that reaches this page can view the Config
tab, which renders the raw contents of config/tiers.yaml and
config/prices.yaml.
"""
from __future__ import annotations
import json
import sys
import uuid
from pathlib import Path

# Ensure project root on path when Streamlit serves this file directly.
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import yaml
import streamlit as st

from src.cost.ledger import aggregate, estimate_cost, load_prices
from src.gateway.features import FeatureExtractor
from src.gateway.models import GatewayRequest, RequestFlags
from src.providers.availability import default_available
from src.route.executor import execute
from src.route.router import load_tiers, route

# ── config ────────────────────────────────────────────────────────────────────

_FEATURES_CFG = _ROOT / "config" / "features.yaml"
_TIERS_CFG    = _ROOT / "config" / "tiers.yaml"
_PRICES_CFG   = _ROOT / "config" / "prices.yaml"
_LOGS_DIR     = _ROOT / "logs" / "usage"


@st.cache_resource  # loaded once per server process, not once per rerun —
# editing config/*.yaml on disk has no effect until this process restarts.
def _load_configs():
    with open(_FEATURES_CFG) as fh:
        feat_cfg = yaml.safe_load(fh)
    tiers_cfg = load_tiers(_TIERS_CFG)
    prices    = load_prices(_PRICES_CFG)
    return feat_cfg, tiers_cfg, prices


def _load_today_events() -> list[dict]:
    # UTC day boundary, matching cost/ledger.py::log_event — see its comment
    # for why "today" here is not local-time midnight.
    from datetime import datetime, timezone
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    path = _LOGS_DIR / f"{day}.jsonl"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(ln) for ln in fh if ln.strip()]


# ── page setup ────────────────────────────────────────────────────────────────

st.set_page_config(page_title="Model Routing Gateway", layout="wide")
st.title("Model Routing Gateway")

tab_play, tab_dash, tab_cfg = st.tabs(["Playground", "Dashboard", "Config"])

feat_cfg, tiers_cfg, prices = _load_configs()
extractor = FeatureExtractor(feat_cfg)

# ── Playground ────────────────────────────────────────────────────────────────

with tab_play:
    col_in, col_out = st.columns([1, 1], gap="large")

    with col_in:
        st.subheader("Request")
        prompt = st.text_area("Prompt", height=180, placeholder="Enter your prompt here…")
        need_json = st.checkbox("Need JSON output")
        tier_choice = st.selectbox("Preferred tier", ["auto", "lite", "mid", "heavy"])
        submitted = st.button("Route & Run", type="primary", use_container_width=True)

    with col_out:
        st.subheader("Result")

        if submitted and prompt.strip():
            request = GatewayRequest(
                id=str(uuid.uuid4()),
                user_text=prompt,
                need_json=need_json,
                preferred_tier=None if tier_choice == "auto" else tier_choice,
                flags=RequestFlags(),
            )

            with st.spinner("Routing…"):
                features = extractor.extract(request)
                decision = route(request, features, tiers_cfg, default_available)

            # Decision section
            with st.expander("Routing decision", expanded=True):
                if decision.status == "ok":
                    st.success(
                        f"**{decision.tier}** tier → `{decision.provider}:{decision.model}`"
                    )
                else:
                    st.error(f"Routing failed: `{decision.status}`")

                st.caption(f"Complexity score: **{features.complexity_score}** "
                           f"({features.complexity_label})")
                if features.keyword_hits:
                    st.caption(f"Keyword hits: {', '.join(features.keyword_hits)}")
                if decision.reason_codes:
                    st.caption("Reason codes: " +
                               ", ".join(r.value for r in decision.reason_codes))
                if decision.fallback_chain:
                    st.caption(f"Fallback chain: {' → '.join(decision.fallback_chain)}")

            if decision.status == "ok":
                with st.spinner("Calling provider…"):
                    response = execute(decision, request, tiers_cfg)

                # Attempts
                with st.expander("Attempts", expanded=False):
                    rows = [
                        {
                            "provider": a.provider,
                            "model": a.model,
                            "ok": a.ok,
                            "latency_ms": round(a.latency_ms, 1),
                            "error": a.error or "",
                        }
                        for a in response.attempts
                    ]
                    st.dataframe(rows, use_container_width=True)

                # Reply
                with st.expander("Reply", expanded=True):
                    if response.ok:
                        if need_json:
                            try:
                                parsed = json.loads(response.text)
                                st.json(parsed)
                            except json.JSONDecodeError:
                                st.text(response.text)
                        else:
                            st.write(response.text)
                    else:
                        st.error(f"All targets failed: {response.error}")

                # Cost
                with st.expander("Cost estimate", expanded=False):
                    if response.ok and response.usage:
                        u = response.usage
                        cost = estimate_cost(
                            response.model or "", u.in_tokens, u.out_tokens, prices
                        )
                        st.metric("In tokens", u.in_tokens)
                        st.metric("Out tokens", u.out_tokens)
                        if cost is None:
                            st.warning(f"Model `{response.model}` not in prices.yaml — UNPRICED")
                        else:
                            st.metric(
                                "Estimated cost (USD)",
                                f"${cost:.6f}",
                                help="Estimate from config/prices.yaml",
                            )
                        if u.approximate:
                            st.caption("Token counts are tiktoken estimates (provider did not report usage).")
                    else:
                        st.info("No usage data (request failed).")

        elif submitted:
            st.warning("Enter a prompt first.")

# ── Dashboard ─────────────────────────────────────────────────────────────────

with tab_dash:
    st.subheader("Today's usage")

    if st.button("Refresh"):
        st.cache_data.clear()

    events = _load_today_events()

    if not events:
        st.info("No events logged today. Run a request in the Playground tab.")
    else:
        agg = aggregate(events)

        # Top metrics
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Requests", agg["n"])
        m2.metric("Fail rate", f"{agg['fail_rate']:.1%}")
        m3.metric("Fallback rate", f"{agg['fallback_rate']:.1%}")
        cost_disp = f"${agg['cost_sum']:.5f}" if agg.get("cost_sum") is not None else "—"
        m4.metric("Total cost (est.)", cost_disp)

        c1, c2 = st.columns(2)

        # Tier distribution
        with c1:
            st.caption("Requests by tier")
            tier_counts: dict[str, int] = {}
            for e in events:
                t = e.get("tier_used") or "unknown"
                tier_counts[t] = tier_counts.get(t, 0) + 1
            # st.bar_chart expects {column: {index: value}} or DataFrame-like
            chart_data = {tier: [count] for tier, count in sorted(tier_counts.items())}
            # Build a simple dict list for st.bar_chart
            st.bar_chart(tier_counts)

        # Cost by tier
        with c2:
            st.caption("Cost by tier (USD est.)")
            cost_by_tier = agg.get("cost_by_tier", {})
            if cost_by_tier:
                st.bar_chart(cost_by_tier)
            else:
                st.info("All calls are Ollama (cost = $0.00).")

        # Detail table
        with st.expander("Event log"):
            display_cols = [
                "ts", "request_id", "tier_used", "model",
                "in_tokens", "out_tokens", "cost", "latency_ms", "fallbacks", "ok",
            ]
            rows = [{k: e.get(k) for k in display_cols} for e in events]
            st.dataframe(rows, use_container_width=True)

        if agg.get("unpriced_count"):
            st.warning(
                f"{agg['unpriced_count']} request(s) succeeded but have no price in "
                "config/prices.yaml (cost=null, flagged UNPRICED)."
            )

# ── Config ────────────────────────────────────────────────────────────────────

with tab_cfg:
    st.subheader("Configuration (read-only)")

    with st.expander("config/tiers.yaml", expanded=True):
        st.code(_TIERS_CFG.read_text(encoding="utf-8"), language="yaml")

    with st.expander("config/prices.yaml", expanded=False):
        st.code(_PRICES_CFG.read_text(encoding="utf-8"), language="yaml")
