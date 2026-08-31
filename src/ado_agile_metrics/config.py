"""Environment-backed application settings."""

from dataclasses import dataclass
import os

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    """Azure DevOps and Microsoft Entra application settings."""

    organization: str
    tenant_id: str
    client_id: str
    client_secret: str
    redirect_uri: str
    api_version: str = "7.1"
    ado_scope: str = "499b84ac-1321-427f-aa17-267ca6975798/user_impersonation"
    admin_pat: str = ""
    reporting_lookback_days: int = 365
    completed_state_names: tuple[str, ...] = ("Accepted", "Closed", "Resolved", "Done", "Completed")
    reporting_time_zone: str = "America/Chicago"

    @property
    def is_configured(self) -> bool:
        """Return whether Entra interactive authentication is configured."""
        return bool(self.organization and self.tenant_id and self.client_id and self.redirect_uri)

    @property
    def pat_fallback_configured(self) -> bool:
        """Return whether the explicitly optional administrator fallback exists."""
        return bool(self.organization and self.admin_pat)


def load_settings() -> Settings:
    """Load settings from the process environment and .env file."""
    load_dotenv()
    return Settings(
        organization=os.getenv("AZDO_ORGANIZATION", "").strip(),
        tenant_id=os.getenv("TENANT_ID", "").strip(),
        client_id=os.getenv("CLIENT_ID", "").strip(),
        client_secret=os.getenv("CLIENT_SECRET", "").strip(),
        redirect_uri=os.getenv("REDIRECT_URI", "http://localhost:8501").strip(),
        api_version=os.getenv("AZDO_API_VERSION", "7.1").strip(),
        ado_scope=os.getenv("AZDO_SCOPE", "499b84ac-1321-427f-aa17-267ca6975798/user_impersonation").strip(),
        admin_pat=os.getenv("AZDO_ADMIN_PAT", "").strip(),
        reporting_lookback_days=int(os.getenv("REPORTING_LOOKBACK_DAYS", "365")),
        completed_state_names=tuple(state.strip() for state in os.getenv("ADO_COMPLETED_STATES", "Accepted,Closed,Resolved,Done,Completed").split(",") if state.strip()),
        reporting_time_zone=os.getenv("AZDO_TIME_ZONE", "America/Chicago").strip(),
    )
