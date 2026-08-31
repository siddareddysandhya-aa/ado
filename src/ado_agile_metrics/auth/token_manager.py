"""MSAL authorization-code flow and secure in-session token retrieval."""

from typing import Any

import msal

from ado_agile_metrics.config import Settings


class TokenManager:
    """Acquire Azure DevOps delegated tokens through Microsoft Entra ID."""

    def __init__(self, settings: Settings, cache: msal.SerializableTokenCache | None = None) -> None:
        self.settings = settings
        self.cache = cache or msal.SerializableTokenCache()
        authority = f"https://login.microsoftonline.com/{settings.tenant_id}"
        self.application = msal.ConfidentialClientApplication(
            client_id=settings.client_id,
            client_credential=settings.client_secret or None,
            authority=authority,
            token_cache=self.cache,
        )

    def authorization_url(self) -> str:
        """Create an OpenID Connect authorization URL with PKCE-capable MSAL state."""
        flow = self.application.initiate_auth_code_flow(
            scopes=[self.settings.ado_scope, "openid", "profile", "offline_access"],
            redirect_uri=self.settings.redirect_uri,
        )
        return flow["auth_uri"]

    def begin_flow(self) -> dict[str, Any]:
        """Create and return MSAL flow state that must stay in the browser session."""
        return self.application.initiate_auth_code_flow(
            scopes=[self.settings.ado_scope, "openid", "profile", "offline_access"],
            redirect_uri=self.settings.redirect_uri,
        )

    def complete_flow(self, flow: dict[str, Any], query_parameters: dict[str, str]) -> dict[str, Any]:
        """Redeem the callback authorization code and return the MSAL token result."""
        return self.application.acquire_token_by_auth_code_flow(flow, query_parameters)

    def silent_token(self, account: dict[str, Any]) -> dict[str, Any] | None:
        """Refresh or obtain the delegated token silently from the in-memory cache."""
        return self.application.acquire_token_silent([self.settings.ado_scope], account)