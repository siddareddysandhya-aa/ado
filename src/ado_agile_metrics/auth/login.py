"""Streamlit login controls for Microsoft Entra ID."""

import msal
import streamlit as st

from ado_agile_metrics.auth.session_manager import SessionManager
from ado_agile_metrics.auth.token_manager import TokenManager
from ado_agile_metrics.config import Settings


def render_login(settings: Settings) -> str | None:
    """Render the sign-in flow and return a delegated Azure DevOps token when available."""
    session = SessionManager(st.session_state)
    if session.access_token:
        account = session.account or {}
        st.sidebar.success(f"Signed in: {account.get('name', account.get('preferred_username', 'Microsoft Entra user'))}")
        if st.sidebar.button("Log out"):
            session.logout()
            st.query_params.clear()
            st.rerun()
        return session.access_token
    if settings.pat_fallback_configured:
        if st.sidebar.button("Use configured PAT"):
            st.session_state["use_admin_pat"] = True
            st.rerun()
        if st.session_state.get("use_admin_pat"):
            st.sidebar.info("Connected with the configured administrator PAT.")
            if st.sidebar.button("Stop using PAT"):
                st.session_state.pop("use_admin_pat", None)
                st.rerun()
    if not settings.is_configured:
        return None
    cache = msal.SerializableTokenCache()
    if serialized_cache := st.session_state.get(SessionManager.CACHE_KEY):
        cache.deserialize(serialized_cache)
    manager = TokenManager(settings, cache)
    callback = dict(st.query_params)
    if "code" in callback and SessionManager.FLOW_KEY in st.session_state:
        result = manager.complete_flow(st.session_state[SessionManager.FLOW_KEY], callback)
        if "access_token" in result:
            session.authenticate(result)
            st.session_state[SessionManager.CACHE_KEY] = cache.serialize()
            st.query_params.clear()
            st.rerun()
        st.error("Microsoft Entra sign-in failed. Confirm app registration and redirect URI.")
        return None
    if st.sidebar.button("Sign in with Microsoft", type="primary"):
        flow = manager.begin_flow()
        st.session_state[SessionManager.FLOW_KEY] = flow
        st.link_button("Continue to Microsoft sign-in", flow["auth_uri"], type="primary")
    return None