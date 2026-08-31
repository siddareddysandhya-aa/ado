"""Framework-neutral authenticated browser-session state management."""

from collections.abc import MutableMapping
from typing import Any


class SessionManager:
    """Keep access tokens and MSAL flow state only in the active Streamlit session."""

    TOKEN_KEY = "entra_token"
    ACCOUNT_KEY = "entra_account"
    FLOW_KEY = "entra_auth_flow"
    CACHE_KEY = "entra_token_cache"

    def __init__(self, state: MutableMapping[str, Any]) -> None:
        self.state = state

    @property
    def access_token(self) -> str | None:
        """Return the current access token without persisting it outside this session."""
        return self.state.get(self.TOKEN_KEY)

    @property
    def account(self) -> dict[str, Any] | None:
        """Return the signed-in account claims retained for the current session."""
        return self.state.get(self.ACCOUNT_KEY)

    def authenticate(self, result: dict[str, Any]) -> None:
        """Store successful MSAL result values only in the current server session."""
        self.state[self.TOKEN_KEY] = result["access_token"]
        self.state[self.ACCOUNT_KEY] = result.get("id_token_claims", {})

    def logout(self) -> None:
        """Clear all authentication artifacts from the browser session."""
        for key in (self.TOKEN_KEY, self.ACCOUNT_KEY, self.FLOW_KEY, self.CACHE_KEY):
            self.state.pop(key, None)