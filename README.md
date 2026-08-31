# Azure DevOps Agile Metrics Portal

A self-service Streamlit portal for configurable Agile metrics from Azure DevOps Analytics OData, with REST discovery and explicit WIQL fallback.

For Windows installation and startup commands, see [RUNBOOK.md](RUNBOOK.md).

## Quick start

1. Create a virtual environment and install dependencies with `pip install -e .[dev]`.
2. Register a Microsoft Entra web application. Add `http://localhost:8501` as a redirect URI and create a client secret for local development.
3. Grant delegated Azure DevOps `user_impersonation` access to the Azure DevOps resource application ID `499b84ac-1321-427f-aa17-267ca6975798`; have an administrator grant consent where required.
4. Copy `.env.example` to `.env` and set `AZDO_ORGANIZATION`, `TENANT_ID`, `CLIENT_ID`, `CLIENT_SECRET`, and `REDIRECT_URI`.
3. Run `streamlit run app.py`.

The sign-in button runs OAuth 2.0 Authorization Code Flow with OpenID Connect through MSAL. Tokens and the MSAL cache exist only in the current Streamlit session. Azure DevOps calls use `Authorization: Bearer <access token>` and automatically discover projects, teams, iterations, areas, types, tags, and users from the connected organization.

`AZDO_ADMIN_PAT` is an optional, administrator-only fallback intended for recovery scenarios. It is not needed for normal Entra-authenticated use and must not be exposed through UI or logs.

## PAT fallback

For direct local access without Entra configuration, set `AZDO_ORGANIZATION` and `AZDO_ADMIN_PAT` in `.env`, restart Streamlit, then choose **Use configured PAT** in the sidebar and select **Azure DevOps** as the data source. The PAT is read from the environment and is never displayed in the application.

## Reporting window

The default Azure DevOps query retrieves work items changed in the last 365 days. Set `REPORTING_LOOKBACK_DAYS` in `.env` to use a different window.

Set `ADO_COMPLETED_STATES` to the comma-separated completed state names used by your Azure DevOps process. The default includes `Accepted`, which is the completed state in many Scrum processes.
