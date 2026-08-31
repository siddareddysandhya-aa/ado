"""Streamlit entry point for the Azure DevOps Agile Metrics Portal."""

from io import BytesIO
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

from ado_agile_metrics.azure_devops import AzureDevOpsClient
from ado_agile_metrics.auth.login import render_login
from ado_agile_metrics.config import load_settings
from ado_agile_metrics.metrics import executive_insights, flow_time_percentiles, kpis, to_frame, velocity_by_iteration, velocity_report
from ado_agile_metrics.query import parse_natural_language
from ado_agile_metrics.reports import pdf_bytes, powerpoint_bytes, send_email_report
from ado_agile_metrics.storage import SnapshotStore


st.set_page_config(page_title="Agile Metrics Portal", page_icon="AM", layout="wide")


@st.cache_data(ttl=300, show_spinner="Refreshing Azure DevOps Analytics data...")
def load_azure_items(settings, access_token: str | None, allow_pat_fallback: bool, project: str, wiql: str):
    """Cache remote retrieval to reduce Azure DevOps API traffic."""
    return AzureDevOpsClient(settings, access_token, allow_pat_fallback).work_items(project, wiql or None)


@st.cache_data(ttl=900, show_spinner="Loading completed Azure DevOps iterations...")
def load_completed_iterations(settings, access_token: str | None, allow_pat_fallback: bool, project: str) -> list[dict[str, object]]:
    """Cache completed iteration metadata that defines each dashboard metric window."""
    return AzureDevOpsClient(settings, access_token, allow_pat_fallback).completed_iterations(project)


@st.cache_data(ttl=900, show_spinner="Loading Azure DevOps Analytics velocity baselines...")
def load_velocity_baselines(settings, access_token: str | None, allow_pat_fallback: bool, project: str, iterations: tuple[str, ...], scope: dict[str, tuple[str, ...]]) -> dict[str, float]:
    """Cache the historical day-one scope used as the planned Velocity baseline."""
    return AzureDevOpsClient(settings, access_token, allow_pat_fallback).analytics_velocity_baselines(project, list(iterations), scope)


@st.cache_data(ttl=900, show_spinner="Reconstructing sprint burndown from work-item history...")
def load_rest_burndown(settings, access_token: str | None, allow_pat_fallback: bool, project: str, iteration: str, work_item_ids: tuple[int, ...], start_date: str, end_date: str) -> list[dict[str, object]]:
    """Cache REST revision reconstruction because it reads one revision stream per work item."""
    return AzureDevOpsClient(settings, access_token, allow_pat_fallback).burndown_history(
        project, iteration, list(work_item_ids), pd.Timestamp(start_date).date(), pd.Timestamp(end_date).date()
    )


@st.cache_data(ttl=900, show_spinner="Loading Azure DevOps Analytics sprint history...")
def load_analytics_burndown(settings, access_token: str | None, allow_pat_fallback: bool, project: str, iteration: str, scope: dict[str, tuple[str, ...]]) -> list[dict[str, object]]:
    """Cache Analytics snapshots used for Azure DevOps-aligned sprint burndown."""
    return AzureDevOpsClient(settings, access_token, allow_pat_fallback).analytics_board_burndown_history(
        project, iteration, scope
    )


def excel_bytes(frame: pd.DataFrame) -> bytes:
    """Serialize selected work items as an Excel workbook."""
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, sheet_name="Work Items")
    return output.getvalue()


def utc_today() -> pd.Timestamp:
    """Return the UTC calendar day used by Azure DevOps iteration date fields."""
    return pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()


def apply_saved_dashboard(store: SnapshotStore) -> None:
    """Restore saved Streamlit widget values before filter widgets are rendered."""
    name = st.session_state.get("saved_dashboard_picker", "Current dashboard")
    if name == "Current dashboard" or name == st.session_state.get("applied_dashboard"):
        return
    configuration = store.load_dashboard(name)
    for key in ("project_filter", "team_filter", "iteration_filter", "area_filter", "type_filter", "assignee_filter", "state_filter", "tag_filter", "metric_filter", "burn_iteration_filter"):
        if key in configuration:
            st.session_state[key] = configuration[key]
    st.session_state["applied_dashboard"] = name


def dashboard_configuration(project: str, teams: list[str], iterations: list[str], areas: list[str], types: list[str], assignees: list[str], states: list[str], tags: list[str], metrics: list[str], burn_iteration: str | None) -> dict[str, object]:
    """Build the reusable filter configuration stored for named and last-used dashboards."""
    return {
        "project_filter": project,
        "team_filter": teams,
        "iteration_filter": iterations,
        "area_filter": areas,
        "type_filter": types,
        "assignee_filter": assignees,
        "state_filter": states,
        "tag_filter": tags,
        "metric_filter": metrics,
        "burn_iteration_filter": burn_iteration,
    }


def render_velocity(frame: pd.DataFrame, iterations: list[str], planned_baselines: dict[str, float]) -> list[go.Figure]:
    """Render the Azure DevOps-style grouped velocity bar chart per sprint."""
    report = velocity_report(frame, iterations, planned_baselines)
    chart = px.bar(
        report,
        x="iteration",
        y=["Planned", "Completed", "Incomplete"],
        barmode="group",
        title="Velocity",
        color_discrete_map={"Planned": "#67B8C8", "Completed": "#167C46", "Incomplete": "#1677C8"},
        labels={"value": "Story Points", "variable": ""},
    )
    st.plotly_chart(chart, use_container_width=True)
    return [chart]


def render_flow_metrics(frame: pd.DataFrame, metric: str, start_date: pd.Timestamp, end_date: pd.Timestamp) -> list[go.Figure]:
    """Render a completed-sprint flow-time control chart with Azure-style trend."""
    column = "lead_time_days" if metric == "Lead Time" else "cycle_time_days"
    completed = frame[frame["is_done"] & frame["completed_date"].between(start_date, end_date)].dropna(subset=[column, "completed_date"]).sort_values("completed_date")
    if completed.empty:
        st.info(f"No completed work items with {metric.lower()} dates match the last two completed sprints.")
        return []
    summary = flow_time_percentiles(completed, column)
    summary_columns = st.columns(4)
    for summary_column, (label, value) in zip(summary_columns, [("Average", summary["average"]), ("Median", summary["median"]), ("P75", summary["p75"]), ("P90", summary["p90"])]):
        summary_column.metric(label, f"{value:.1f} days")
    trend = px.scatter(completed, x="completed_date", y=column, color="work_item_type", title=f"{metric} Trend")
    daily_average = completed.groupby(completed["completed_date"].dt.normalize(), as_index=False)[column].mean()
    moving_window_days = max(1, int((end_date - start_date).days * 0.2) // 2 * 2 - 1)
    daily_average["moving_average"] = daily_average[column].rolling(window=moving_window_days, min_periods=1).mean()
    trend.add_scatter(x=daily_average["completed_date"], y=daily_average["moving_average"], mode="lines", name="5-day moving average", line={"color": "#16826c", "width": 3})
    st.plotly_chart(trend, use_container_width=True)
    return [trend]


def render_burndown(frame: pd.DataFrame, iteration: str, burnup: bool = False, history: list[dict[str, object]] | None = None) -> list[go.Figure]:
    """Render a single selected iteration's burnup or burndown series."""
    if history is not None and not history:
        st.info("Azure DevOps Analytics found no board snapshots for the selected Team, Area Path, and sprint. Select the Azure DevOps team that owns this board or broaden the filters.")
        return []
    selected = frame[frame["iteration"] == iteration]
    if selected.empty:
        st.info("No work items match the selected burndown iteration.")
        return []
    scope = selected["remaining_work"].sum()
    measure = "Remaining Work"
    if not scope:
        scope = selected["story_points"].sum()
        measure = "Story Points"
    if not scope:
        st.info("This iteration has no Remaining Work or Story Points to burn down.")
        return []
    iteration_start = selected["iteration_start"].dropna().min()
    iteration_end = selected["iteration_end"].dropna().max()
    start_date = iteration_start if pd.notna(iteration_start) else selected["created_date"].dropna().min()
    end_date = iteration_end if pd.notna(iteration_end) else utc_today()
    if pd.isna(start_date):
        st.info("This iteration has no configured start date or work-item creation dates for a burndown timeline.")
        return []
    if history:
        historical = pd.DataFrame(history)
        title = f"{iteration} {'Burnup' if burnup else 'Burndown'}"
        if burnup:
            historical["completed"] = historical["scope"] - historical["remaining"]
            figure = px.area(historical, x="date", y="completed", title=title, labels={"date": "Date", "completed": "Story Points"})
            figure.add_scatter(x=historical["date"], y=historical["scope"], mode="lines", name="Total Scope", line={"color": "#6b7280"})
        else:
            figure = px.area(historical, x="date", y="remaining", title=title, labels={"date": "Date", "remaining": "Story Points"})
            figure.add_scatter(x=[historical["date"].iloc[0], historical["date"].iloc[-1]], y=[historical["scope"].iloc[0], 0], mode="lines", name="Ideal Trend", line={"dash": "dash"})
        st.plotly_chart(figure, use_container_width=True)
        st.caption("REST revision reconstruction using UTC end-of-day values. It includes daily Story Point scope and remaining work; Azure Analytics capacity data is not available through this fallback.")
        return [figure]
    dates = pd.date_range(start_date, end_date)
    values = []
    for current_date in dates:
        delivered = selected.loc[selected["completed_date"].le(current_date), "remaining_work"].sum()
        if not delivered and measure == "Story Points":
            delivered = selected.loc[selected["completed_date"].le(current_date), "story_points"].sum()
        values.append(delivered if burnup else max(scope - delivered, 0))
    title = f"{iteration} {'Burnup' if burnup else 'Burndown'}"
    figure = px.line(x=dates, y=values, title=title, labels={"x": "Date", "y": measure})
    if not burnup:
        figure.add_scatter(x=[dates[0], dates[-1]], y=[scope, 0], mode="lines", name="Ideal")
    st.plotly_chart(figure, use_container_width=True)
    st.caption("Current-state approximation using UTC day boundaries. Azure DevOps's built-in chart uses historical Analytics snapshots, including daily scope and Remaining Work changes.")
    return [figure]


def render_work_item_analytics(frame: pd.DataFrame) -> list[go.Figure]:
    """Render work-item status, type, and assignee breakdowns."""
    status = px.bar(frame, x="state", title="Status Breakdown")
    types = px.pie(frame, names="work_item_type", title="Work Item Type Breakdown")
    assignees = px.bar(frame.groupby("assignee", as_index=False).size(), x="assignee", y="size", title="Assignee Breakdown")
    for figure in (status, types, assignees):
        st.plotly_chart(figure, use_container_width=True)
    return [status, types, assignees]


def main() -> None:
    """Render the configurable analytics experience."""
    settings = load_settings()
    store = SnapshotStore(Path("data/metrics.db"))
    if "last_used_filters_loaded" not in st.session_state:
        for key, value in store.load_last_used().items():
            st.session_state.setdefault(key, value)
        st.session_state["last_used_filters_loaded"] = True
    st.title("Agile Metrics Portal")
    st.caption("Azure DevOps delivery intelligence for teams and leadership")
    access_token = render_login(settings)
    use_pat_fallback = bool(st.session_state.get("use_admin_pat"))

    page = st.sidebar.radio("Workspace", ["Dashboard", "Connection Status"])
    if page == "Connection Status":
        st.header("Connection Status")
        if not access_token and not use_pat_fallback:
            st.warning("Sign in with Microsoft or use a configured administrator PAT to validate the connection.")
            return
        client = AzureDevOpsClient(settings, access_token, use_pat_fallback)
        try:
            projects = client.projects()
            project = st.selectbox("Project to test", projects)
            if st.button("Test connection", type="primary"):
                discovery = client.discovery(project)
                try:
                    analytics = client.analytics_available(project)
                except requests.HTTPError as error:
                    if error.response is None or error.response.status_code != 403:
                        raise
                    analytics = False
                st.success("Connected successfully")
                st.json({"organization": settings.organization, "projects_found": len(projects), "analytics_feed": "Available" if analytics else "Unavailable", "teams_found": len(discovery.teams), "iterations_found": len(discovery.iterations)})
                if not analytics:
                    st.warning("Analytics OData is unavailable for this PAT. Dashboard data will use the Azure DevOps REST/WIQL fallback.")
        except requests.Timeout:
            st.error("Azure DevOps did not respond within 30 seconds. Check your network, VPN, proxy, or firewall access to dev.azure.com, then try again.")
        except requests.HTTPError as error:
            status_code = error.response.status_code if error.response is not None else "unknown"
            st.error(f"Azure DevOps rejected the connection (HTTP {status_code}). Check PAT scope and organization access.")
        except requests.RequestException:
            st.error("Azure DevOps could not be reached. Check your organization URL, network, VPN, proxy, or firewall settings.")
        except Exception as error:
            st.error(f"Connection could not be verified: {type(error).__name__}. Confirm organization access and network connectivity.")
        return

    with st.sidebar:
        st.header("Data & Filters")
        saved_names = store.dashboard_names()
        st.selectbox("Open saved dashboard", ["Current dashboard", *saved_names], key="saved_dashboard_picker", on_change=apply_saved_dashboard, args=(store,))
        if not saved_names:
            st.caption("No saved dashboards yet. Save the current configuration from Save & Export.")
        if not access_token and not use_pat_fallback:
            st.warning("Azure DevOps access is required. Click Use configured PAT to load live data.")
            st.stop()
        mode = "Azure DevOps"
        client = AzureDevOpsClient(settings, access_token, use_pat_fallback)
        try:
            projects = client.projects()
        except requests.RequestException:
            st.error("Azure DevOps projects could not be loaded. Check your connection and PAT access, then refresh.")
            return
        project = st.selectbox("Project", projects, key="project_filter")
        try:
            discovery = client.discovery(project)
        except requests.RequestException:
            st.warning("Some filter options could not be discovered. Showing values from retrieved work items instead.")
            discovery = None
        if st.button("Refresh Azure data"):
            load_azure_items.clear()
            load_completed_iterations.clear()
        try:
            completed_iteration_metadata = load_completed_iterations(settings, access_token, use_pat_fallback, project)
            if not completed_iteration_metadata:
                st.error("Azure DevOps Analytics returned no completed iterations for this project.")
                return
            items = load_azure_items(settings, access_token, use_pat_fallback, project, "")
        except requests.HTTPError as error:
            status_code = error.response.status_code if error.response is not None else "unknown"
            st.error(f"Azure DevOps Analytics could not load reporting data (HTTP {status_code}). Check Analytics access and retry.")
            return
        except requests.RequestException:
            st.error("Azure DevOps work items could not be loaded. Check your network connection and retry.")
            return
        completed_states = getattr(settings, "completed_state_names", ("Accepted", "Closed", "Resolved", "Done", "Completed"))
        frame = to_frame(items)
        frame["is_done"] = frame["is_done"] | frame["state"].str.lower().isin({state.lower() for state in completed_states})
        if frame.empty:
            st.error("No work items were returned for this project or query.")
            return
        team_values = sorted(set(frame["team"]) | set(discovery.teams if discovery else []))
        iteration_values = sorted(set(frame["iteration"]) | set(discovery.iterations if discovery else []))
        area_values = sorted(set(frame["area_path"]) | set(discovery.areas if discovery else []))
        type_values = sorted(set(frame["work_item_type"]) | set(discovery.work_item_types if discovery else []))
        teams = st.multiselect("Team / Squad", discovery.teams if discovery else team_values, default=[], key="team_filter")
        completed_iterations = [item["name"] for item in completed_iteration_metadata]
        velocity_iterations = completed_iterations[-6:]
        flow_iterations = completed_iterations[-2:]
        burndown_iteration = completed_iterations[-1]
        st.caption(f"Automated windows: Velocity uses {len(velocity_iterations)} completed sprints; Burndown uses {burndown_iteration}; Lead/Cycle use the latest {len(flow_iterations)} completed sprints.")
        iterations = velocity_iterations
        areas = st.multiselect("Area Path", area_values, default=[], key="area_filter")
        types = st.multiselect("Work Item Type", type_values, default=sorted(frame["work_item_type"].unique()), key="type_filter")
        assignees = st.multiselect("Assignees", sorted(frame["assignee"].unique()), default=sorted(frame["assignee"].unique()), key="assignee_filter")
        states = sorted(frame["state"].unique())
        tag_values = sorted({tag for value in frame["tags"] for tag in value.split("; ") if tag} | set(discovery.tags if discovery else []))
        tags = st.multiselect("Tags", tag_values, key="tag_filter")
        natural_language = st.text_input("Ask analytics", placeholder="Example: Show velocity trend for Sprint 42 tagged Constraint6")
        if natural_language:
            intent = parse_natural_language(natural_language)
            if intent.metric:
                st.caption(f"Recognized metric: {intent.metric}. Refine the filters below before generating.")
        selected_metrics = st.multiselect("Dashboard metrics", ["Velocity", "Burndown", "Lead Time", "Cycle Time"], default=["Velocity", "Burndown", "Lead Time", "Cycle Time"], key="metric_filter")
        sprint_metric_selected = "Burndown" in selected_metrics
        sprint_for_burn = None

    if not areas:
        st.info("Select an Area Path to generate the Azure DevOps Analytics charts.")
        return
    if not teams:
        st.info("Select a Team / Squad to generate the Azure DevOps Analytics charts.")
        return

    metric_base = frame[
        frame["area_path"].isin(areas) &
        frame["work_item_type"].isin(types) & frame["assignee"].isin(assignees)
    ].copy()
    if tags:
        metric_base = metric_base[metric_base["tags"].apply(lambda value: any(tag in value.split("; ") for tag in tags))]
    if metric_base.empty:
        st.warning("No work items match the selected filters.")
        return

    analytics_scope = {
        "teams": tuple(teams),
        "areas": tuple(areas),
        "work_item_types": tuple(types),
        "assignees": tuple(assignees),
        "tags": tuple(tags),
    }

    if sprint_metric_selected:
        sprint_for_burn = burndown_iteration

    burndown_history = None
    burndown_source = ""
    if sprint_for_burn and mode == "Azure DevOps":
        try:
            burndown_history = load_analytics_burndown(settings, access_token, use_pat_fallback, project, sprint_for_burn, analytics_scope)
            burndown_source = "Analytics OData snapshots"
        except requests.RequestException:
            st.warning("Azure DevOps Analytics snapshots could not be retrieved for this sprint. No Burndown approximation is shown.")

    if {"Lead Time", "Cycle Time"}.intersection(selected_metrics) and not metric_base["is_done"].any():
        st.warning("Lead and cycle time need completed work items. Clear the State filter or include a configured completed state such as Accepted.")

    flow_start = pd.Timestamp(completed_iteration_metadata[-2 if len(completed_iteration_metadata) >= 2 else -1]["start"])
    flow_end = pd.Timestamp(completed_iteration_metadata[-1]["end"])
    flow_filtered = metric_base
    burndown_filtered = metric_base[metric_base["iteration"] == burndown_iteration]
    filtered = metric_base
    try:
        velocity_baselines = load_velocity_baselines(settings, access_token, use_pat_fallback, project, tuple(velocity_iterations), analytics_scope)
    except requests.RequestException:
        st.error("Azure DevOps Analytics could not load the Velocity planning baselines.")
        return

    values = kpis(filtered)
    values["velocity"] = float(velocity_by_iteration(metric_base, velocity_iterations)["completed_story_points"].mean())
    values["lead_time"] = flow_time_percentiles(flow_filtered, "lead_time_days", flow_start, flow_end)["average"]
    values["cycle_time"] = flow_time_percentiles(flow_filtered, "cycle_time_days", flow_start, flow_end)["average"]
    current_configuration = dashboard_configuration(project, teams, iterations, areas, types, assignees, states, tags, selected_metrics, sprint_for_burn)
    store.save_last_used(current_configuration)
    store.snapshot(project, values)
    columns = st.columns(3)
    for column, (label, value, suffix) in zip(columns, [("Velocity", values["velocity"], " SP"), ("Lead Time", values["lead_time"], " days"), ("Cycle Time", values["cycle_time"], " days")]):
        column.metric(label, f"{value:.1f}{suffix}")

    figures: list[go.Figure] = []
    if selected_metrics:
        for metric, tab in zip(selected_metrics, st.tabs(selected_metrics)):
            with tab:
                if metric == "Velocity" or metric == "Predictability":
                    figures.extend(render_velocity(metric_base, velocity_iterations, velocity_baselines))
                elif metric == "Burndown":
                    figures.extend(render_burndown(burndown_filtered, sprint_for_burn, history=burndown_history))
                    if burndown_source:
                        st.caption(f"Data source: {burndown_source}.")
                elif metric in {"Lead Time", "Cycle Time"}:
                    st.caption("Completed work from the last two completed sprints.")
                    figures.extend(render_flow_metrics(flow_filtered, metric, flow_start, flow_end))

    st.header("Executive Summary")
    for insight in executive_insights(filtered):
        st.write(f"- {insight}")

    with st.expander("Save & Export"):
        name = st.text_input("Dashboard name", placeholder="Leadership Dashboard")
        if st.button("Save dashboard") and name:
            store.save_dashboard(name, current_configuration)
            st.success(f"Saved {name}.")
        st.caption("Saved: " + (", ".join(store.dashboard_names()) or "None. Enter a dashboard name and select Save dashboard."))
        st.download_button("CSV", filtered.to_csv(index=False).encode(), "work-items.csv", "text/csv")
        st.download_button("Excel", excel_bytes(filtered), "work-items.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        summary = executive_insights(filtered)
        leadership_pdf = pdf_bytes("Agile Metrics Leadership Summary", values, summary)
        st.download_button("PDF summary", leadership_pdf, "agile-metrics-summary.pdf", "application/pdf")
        powerpoint_context = {
            "project": project,
            "squad": ", ".join(teams),
            "area_path": ", ".join(areas),
            "sprint": sprint_for_burn or ", ".join(iterations),
        }
        st.download_button("PowerPoint with charts", powerpoint_bytes("Agile Metrics Leadership Summary", values, summary, figures, powerpoint_context), "agile-metrics-charts.pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation")
        recipient = st.text_input("Leadership email recipient")
        if st.button("Email leadership report") and recipient:
            try:
                send_email_report(recipient, "Agile Metrics Leadership Summary", summary, leadership_pdf)
                st.success("Leadership report sent.")
            except ValueError as error:
                st.warning(str(error))
            except Exception:
                st.error("The email report could not be sent. Verify SMTP configuration and recipient address.")
        if figures:
            try:
                st.download_button("PNG chart", figures[0].to_image(format="png"), "metric-chart.png", "image/png")
            except ValueError:
                st.caption("Install Kaleido to enable PNG chart export.")


if __name__ == "__main__":
    main()