from ado_agile_metrics.auth.session_manager import SessionManager
from ado_agile_metrics.config import Settings


def test_settings_prefer_entra_configuration_and_make_pat_optional():
    settings = Settings("https://dev.azure.com/example", "tenant", "client", "", "http://localhost:8501")

    assert settings.is_configured
    assert not settings.pat_fallback_configured


def test_session_manager_only_uses_provided_session_state():
    state = {}
    session = SessionManager(state)

    session.authenticate({"access_token": "not-persisted", "id_token_claims": {"name": "Avery"}})

    assert session.access_token == "not-persisted"
    assert session.account == {"name": "Avery"}
    session.logout()
    assert session.access_token is None