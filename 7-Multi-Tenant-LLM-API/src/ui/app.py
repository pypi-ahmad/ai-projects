"""Streamlit admin UI -- a thin HTTP client of this project's own admin
API (src/api/admin_routes.py). It never touches the DB directly and has no
route to read prompt_logs (no such endpoint exists at all), so there is no
way for it to show one tenant's prompt/response text to an admin browsing
another tenant, regardless of that tenant's store_prompts flag -- see
docs/THREAT_NOTES.md.
"""

from __future__ import annotations

import httpx
import streamlit as st

st.set_page_config(page_title="LLM Gateway Admin")

if "admin_token" not in st.session_state:
    st.session_state.admin_token = ""
if "api_base_url" not in st.session_state:
    st.session_state.api_base_url = "http://127.0.0.1:8000"
if "tenant_id" not in st.session_state:
    st.session_state.tenant_id = ""

st.title("LLM gateway admin", icon=":material/admin_panel_settings:")

with st.sidebar:
    st.session_state.api_base_url = st.text_input("API base URL", value=st.session_state.api_base_url)
    # type="password" masks display; the value only ever lives in this
    # session's memory (session_state) and is sent as a header on requests
    # this browser session makes -- nothing here logs or prints it.
    st.session_state.admin_token = st.text_input(
        "Admin token", type="password", value=st.session_state.admin_token
    )


def _headers() -> dict[str, str]:
    return {"X-Admin-Token": st.session_state.admin_token}


def _get(path: str) -> httpx.Response:
    return httpx.get(f"{st.session_state.api_base_url}{path}", headers=_headers(), timeout=10)


def _post(path: str, json: dict | None = None) -> httpx.Response:
    return httpx.post(f"{st.session_state.api_base_url}{path}", headers=_headers(), json=json, timeout=10)


def _show_error(resp: httpx.Response) -> None:
    try:
        st.error(resp.json())
    except ValueError:
        st.error(f"{resp.status_code}: {resp.text}")


if not st.session_state.admin_token:
    st.info("Enter the admin token in the sidebar to continue.")
    st.stop()

tab_create, tab_keys, tab_limits, tab_usage = st.tabs(["Create tenant", "Keys", "Limits & status", "Usage"])

with tab_create:
    with st.form("create_tenant_form"):
        name = st.text_input("Tenant name")
        submitted = st.form_submit_button("Create tenant")
    if submitted:
        resp = _post("/admin/tenants", json={"name": name})
        if resp.status_code == 200:
            tenant = resp.json()
            st.session_state.tenant_id = tenant["id"]
            st.success(f"Created tenant {tenant['name']} ({tenant['id']})")
        else:
            _show_error(resp)

st.divider()
# Free-text, not a dropdown: there is no list-tenants admin route to
# populate one from (src/api/admin_routes.py has no GET "" route).
# "Create tenant" above fills this in for convenience; otherwise the admin
# must already know the tenant_id (e.g. from its create-tenant response).
st.session_state.tenant_id = st.text_input(
    "Tenant ID (target of the actions below)", value=st.session_state.tenant_id
)

with tab_keys:
    with st.form("create_key_form"):
        key_name = st.text_input("Key name", value="key")
        submitted_key = st.form_submit_button("Create key")
    if submitted_key:
        resp = _post(f"/admin/tenants/{st.session_state.tenant_id}/keys", json={"name": key_name})
        if resp.status_code == 200:
            body = resp.json()
            st.warning("Raw key shown once -- copy it now, it cannot be retrieved again.")
            st.code(body["raw_key"])
        else:
            _show_error(resp)

    with st.form("revoke_key_form"):
        key_id = st.text_input("Key ID to revoke")
        submitted_revoke = st.form_submit_button("Revoke key")
    if submitted_revoke:
        resp = _post(f"/admin/tenants/{st.session_state.tenant_id}/keys/{key_id}/revoke")
        if resp.status_code == 200:
            st.success("Key revoked.")
        else:
            _show_error(resp)

with tab_limits:
    with st.form("limits_form"):
        rpm = st.number_input("Requests per minute", min_value=1, value=60)
        rpd = st.number_input("Requests per day", min_value=1, value=5000)
        max_tokens_per_req = st.number_input("Max tokens per request", min_value=1, value=4096)
        token_budget_month = st.number_input("Monthly token budget", min_value=1, value=1_000_000)
        budget_reset_day = st.number_input("Budget reset day (1-28)", min_value=1, max_value=28, value=1)
        allowed_models_text = st.text_area("Allowed models (one per line)", value="granite4.1:3b")
        allowed_providers_text = st.text_area("Allowed providers (one per line)", value="ollama")
        submitted_limits = st.form_submit_button("Save limits")
    if submitted_limits:
        payload = {
            "rpm": int(rpm),
            "rpd": int(rpd),
            "max_tokens_per_req": int(max_tokens_per_req),
            "token_budget_month": int(token_budget_month),
            "budget_reset_day": int(budget_reset_day),
            "allowed_models": [m.strip() for m in allowed_models_text.splitlines() if m.strip()],
            "allowed_providers": [p.strip() for p in allowed_providers_text.splitlines() if p.strip()],
        }
        resp = _post(f"/admin/tenants/{st.session_state.tenant_id}/limits", json=payload)
        if resp.status_code == 200:
            st.success("Limits updated.")
        else:
            _show_error(resp)

    if st.button("Suspend tenant", icon=":material/block:"):
        resp = _post(f"/admin/tenants/{st.session_state.tenant_id}/suspend")
        if resp.status_code == 200:
            st.success("Tenant suspended.")
        else:
            _show_error(resp)

with tab_usage:
    if st.button("Refresh usage", icon=":material/refresh:"):
        resp = _get(f"/admin/tenants/{st.session_state.tenant_id}/usage")
        if resp.status_code == 200:
            report = resp.json()
            quota = report["quota"]
            row = st.container(horizontal=True)
            row.metric("RPM", f"{quota['rpm_used']}/{quota['rpm_limit']}")
            row.metric("RPD", f"{quota['rpd_used']}/{quota['rpd_limit']}")
            row.metric(
                "Monthly tokens", f"{quota['month_tokens_used']}/{quota['month_tokens_limit']}"
            )
            # Metadata only -- no prompt/response text exists in this
            # table or anywhere this UI can reach (see module docstring).
            st.dataframe(report["recent_events"], width="stretch")
        else:
            _show_error(resp)
