"""Azure DevOps REST client and work-item normalization."""

from base64 import b64encode
from datetime import date, datetime, timedelta, timezone
from dataclasses import dataclass
from typing import Any

import pandas as pd
import requests

from .config import Settings
from .models import WorkItem


class AzureDevOpsClient:
    """OData-first reporting client with REST metadata and WIQL fallback."""

    def __init__(self, settings: Settings, access_token: str | None = None, allow_pat_fallback: bool = False) -> None:
        self.settings = settings
        organization = settings.organization.removeprefix("https://dev.azure.com/").strip("/")
        self.base_url = f"https://dev.azure.com/{organization}"
        self.analytics_url = f"https://analytics.dev.azure.com/{organization}"
        self.session = requests.Session()
        if access_token:
            self.session.headers.update({"Authorization": f"Bearer {access_token}"})
        elif allow_pat_fallback and settings.pat_fallback_configured:
            credential = b64encode(f":{settings.admin_pat}".encode()).decode()
            self.session.headers.update({"Authorization": f"Basic {credential}"})
        else:
            raise ValueError("A Microsoft Entra access token is required. PAT fallback is administrator-only.")

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        supplied_params = kwargs.pop("params", {})
        response = self.session.request(
            method,
            f"{self.base_url}/{path}",
            params={"api-version": self.settings.api_version, **supplied_params},
            timeout=30,
            **kwargs,
        )
        response.raise_for_status()
        return response.json()

    def _analytics_request(self, project: str, entity: str, params: dict[str, str]) -> dict[str, Any]:
        response = self.session.get(
            f"{self.analytics_url}/{project}/_odata/v4.0-preview/{entity}",
            params=params,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def projects(self) -> list[str]:
        """Return available project names."""
        return [item["name"] for item in self._request("GET", "_apis/projects").get("value", [])]

    def teams(self, project: str) -> list[str]:
        """Return team names for a project."""
        return [item["name"] for item in self._request("GET", f"_apis/projects/{project}/teams").get("value", [])]

    def discovery(self, project: str) -> "Discovery":
        """Discover dynamic filter options from the selected project's live metadata."""
        teams = self.teams(project)
        iterations = self._request("GET", f"{project}/_apis/wit/classificationnodes/iterations", params={"$depth": "10"})
        areas = self._request("GET", f"{project}/_apis/wit/classificationnodes/areas", params={"$depth": "10"})
        types = self._request("GET", f"{project}/_apis/wit/workitemtypes").get("value", [])
        tags = self._request("GET", f"{project}/_apis/wit/tags").get("value", [])
        return Discovery(
            teams=teams,
            iterations=_classification_names(iterations),
            areas=_classification_names(areas),
            work_item_types=[item["name"] for item in types],
            tags=[item["name"] for item in tags],
        )

    def work_items(self, project: str, wiql: str | None = None) -> list[WorkItem]:
        """Fetch reporting data from Analytics OData; WIQL is retained for admin diagnostics."""
        if not wiql:
            return self.analytics_work_items(project)
        query = wiql or (
            "SELECT [System.Id], [System.ChangedDate] FROM WorkItems "
            f"WHERE [System.TeamProject] = '{project.replace("'", "''")}' "
            f"AND [System.ChangedDate] >= @Today - {self.settings.reporting_lookback_days} "
            "ORDER BY [System.ChangedDate] DESC"
        )
        result = self._request(
            "POST",
            f"{project}/_apis/wit/wiql",
            params={"$top": "10000"},
            json={"query": query},
        )
        identifiers = [item["id"] for item in result.get("workItems", [])]
        if not identifiers:
            return []
        fields = [
            "System.Title", "System.TeamProject", "System.IterationPath", "System.WorkItemType",
            "System.State", "System.AssignedTo", "System.AreaPath", "System.Tags", "System.CreatedDate",
            "Microsoft.VSTS.Scheduling.StoryPoints", "Microsoft.VSTS.Scheduling.RemainingWork",
            "Microsoft.VSTS.Common.ActivatedDate", "Microsoft.VSTS.Common.ClosedDate",
            "Microsoft.VSTS.Common.ResolvedDate",
        ]
        state_categories = self._state_categories(project)
        iteration_windows = self._iteration_windows(project)
        items: list[WorkItem] = []
        for offset in range(0, len(identifiers), 200):
            batch = self._request(
                "GET", "_apis/wit/workitems",
                params={"ids": ",".join(map(str, identifiers[offset:offset + 200])), "fields": ",".join(fields)},
            )
            items.extend(self._normalize(item, project, state_categories, iteration_windows) for item in batch.get("value", []))
        return items

    def _state_categories(self, project: str) -> dict[tuple[str, str], str]:
        """Map each process-specific state to its Azure Boards workflow category."""
        categories: dict[tuple[str, str], str] = {}
        for item_type in self._request("GET", f"{project}/_apis/wit/workitemtypes").get("value", []):
            states = self._request("GET", f"{project}/_apis/wit/workitemtypes/{item_type['name']}/states").get("value", [])
            categories.update({(item_type["name"], state["name"]): state.get("category", "") for state in states})
        return categories

    def _iteration_windows(self, project: str) -> list[tuple[str, date, date]]:
        """Read configured sprint dates for completion-date velocity attribution."""
        tree = self._request("GET", f"{project}/_apis/wit/classificationnodes/iterations", params={"$depth": "10"})
        return _classification_windows(tree)

    def burndown_history(self, project: str, iteration: str, work_item_ids: list[int], start_date: date, end_date: date) -> list[dict[str, object]]:
        """Reconstruct daily Story Point scope and remaining work from REST revisions."""
        state_categories = self._state_categories(project)
        revisions = [self._request("GET", f"{project}/_apis/wit/workitems/{work_item_id}/revisions").get("value", []) for work_item_id in work_item_ids]
        history: list[dict[str, object]] = []
        for current_date in pd.date_range(start_date, end_date):
            day_end = current_date.to_pydatetime().replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
            scope = 0.0
            remaining = 0.0
            for item_revisions in revisions:
                revision = _revision_at_day_end(item_revisions, day_end)
                if revision is None:
                    continue
                fields = revision.get("fields", {})
                assigned_iteration = str(fields.get("System.IterationPath", "")).split("\\")[-1]
                if assigned_iteration != iteration:
                    continue
                points = float(fields.get("Microsoft.VSTS.Scheduling.StoryPoints") or 0)
                scope += points
                item_type = fields.get("System.WorkItemType", "Unknown")
                state = fields.get("System.State", "Unknown")
                is_completed = state_categories.get((item_type, state), "").lower() == "completed" or state.lower() in {value.lower() for value in self.settings.completed_state_names}
                if not is_completed:
                    remaining += points
            history.append({"date": current_date, "scope": scope, "remaining": remaining})
        return history

    def analytics_burndown_history(self, project: str, iteration: str, start_date: date | None = None, end_date: date | None = None, scope: dict[str, tuple[str, ...]] | None = None) -> list[dict[str, object]]:
        """Aggregate authoritative daily sprint snapshots from Azure DevOps Analytics OData."""
        iterations = self._analytics_request(
            project,
            "Iterations",
            {
                "$select": "IterationSK,IterationName,StartDate,EndDate",
                "$filter": f"IterationName eq '{iteration.replace("'", "''")}'",
                "$top": "20",
            },
        ).get("value", [])
        matching_iteration = next(
            (
                item
                for item in iterations
                if start_date is None or (self._date(item.get("StartDate")) == start_date and self._date(item.get("EndDate")) == end_date)
            ),
            None,
        )
        if matching_iteration is None:
            return []
        start_date = self._date(matching_iteration.get("StartDate"))
        end_date = self._date(matching_iteration.get("EndDate"))
        if start_date is None or end_date is None:
            return []
        snapshot_end_date = end_date + timedelta(days=1) if self.settings.reporting_time_zone.startswith("America/") else end_date
        response = self._analytics_request(
            project,
            "WorkItemSnapshot",
            {
                "$select": "DateValue,StoryPoints,StateCategory,State,WorkItemType,TagNames",
                "$expand": "Area($select=AreaPath),AssignedTo($select=UserName)",
                "$filter": f"IterationSK eq {matching_iteration['IterationSK']} and DateValue ge {start_date.isoformat()} and DateValue le {snapshot_end_date.isoformat()}",
                "$top": "100000",
            },
        )
        snapshots = pd.DataFrame(response.get("value", []))
        if snapshots.empty:
            return []
        if scope:
            if scope.get("areas"):
                snapshots = snapshots[snapshots["Area"].apply(lambda value: isinstance(value, dict) and value.get("AreaPath") in scope["areas"])]
            if scope.get("work_item_types"):
                snapshots = snapshots[snapshots["WorkItemType"].isin(scope["work_item_types"])]
            if scope.get("assignees"):
                snapshots = snapshots[snapshots["AssignedTo"].apply(lambda value: isinstance(value, dict) and value.get("UserName") in scope["assignees"])]
            if scope.get("tags"):
                snapshots = snapshots[snapshots["TagNames"].fillna("").apply(lambda value: any(tag in str(value).split("; ") for tag in scope["tags"]))]
        if snapshots.empty:
            return []
        snapshots["date"] = (
            pd.to_datetime(snapshots["DateValue"], utc=True)
            .dt.tz_convert(self.settings.reporting_time_zone)
            .dt.normalize()
            .dt.tz_localize(None)
            .clip(upper=pd.Timestamp(end_date))
        )
        snapshots["story_points"] = pd.to_numeric(snapshots["StoryPoints"], errors="coerce").fillna(0.0)
        completed = snapshots["StateCategory"].fillna("").str.lower().eq("completed") | snapshots["State"].fillna("").str.lower().isin({value.lower() for value in self.settings.completed_state_names})
        history = snapshots.groupby("date", as_index=False).agg(scope=("story_points", "sum"))
        remaining = snapshots.loc[~completed].groupby("date", as_index=False).agg(remaining=("story_points", "sum"))
        return history.merge(remaining, on="date", how="left").fillna({"remaining": 0.0}).to_dict("records")

    def analytics_board_burndown_history(self, project: str, iteration: str, scope: dict[str, tuple[str, ...]]) -> list[dict[str, object]]:
        """Aggregate the selected team's board snapshots for Azure-aligned sprint Burndown."""
        iterations = self._analytics_request(
            project,
            "Iterations",
            {"$select": "IterationSK,IterationName,StartDate,EndDate", "$filter": f"IterationName eq '{iteration.replace("'", "''")}'", "$top": "20"},
        ).get("value", [])
        matching_iteration = next((item for item in iterations if item.get("StartDate") and item.get("EndDate")), None)
        if matching_iteration is None:
            return []
        start_date = self._date(matching_iteration["StartDate"])
        end_date = self._date(matching_iteration["EndDate"])
        if start_date is None or end_date is None:
            return []
        team_names = scope.get("teams", ())
        if len(team_names) != 1:
            return []
        teams = self._analytics_request(
            project,
            "Teams",
            {"$select": "TeamSK,TeamName", "$filter": f"TeamName eq '{team_names[0].replace("'", "''")}'", "$top": "2"},
        ).get("value", [])
        if not teams:
            return []
        response = self._analytics_request(
            project,
            "WorkItemBoardSnapshot",
            {
                "$select": "DateValue,StoryPoints,IsDone,WorkItemType,TagNames",
                "$expand": "Area($select=AreaPath),AssignedTo($select=UserName)",
                "$filter": f"TeamSK eq {teams[0]['TeamSK']} and IterationSK eq {matching_iteration['IterationSK']} and DateValue ge {start_date.isoformat()} and DateValue le {end_date.isoformat()}",
                "$top": "100000",
            },
        )
        snapshots = pd.DataFrame(response.get("value", []))
        if snapshots.empty:
            return []
        if scope.get("areas"):
            snapshots = snapshots[snapshots["Area"].apply(lambda value: isinstance(value, dict) and value.get("AreaPath") in scope["areas"])]
        if scope.get("work_item_types"):
            snapshots = snapshots[snapshots["WorkItemType"].isin(scope["work_item_types"])]
        if scope.get("assignees"):
            snapshots = snapshots[snapshots["AssignedTo"].apply(lambda value: isinstance(value, dict) and value.get("UserName") in scope["assignees"])]
        if scope.get("tags"):
            snapshots = snapshots[snapshots["TagNames"].fillna("").apply(lambda value: any(tag in str(value).split("; ") for tag in scope["tags"]))]
        if snapshots.empty:
            return []
        snapshots["date"] = pd.to_datetime(snapshots["DateValue"], utc=True).dt.tz_convert(self.settings.reporting_time_zone).dt.normalize().dt.tz_localize(None)
        snapshots["story_points"] = pd.to_numeric(snapshots["StoryPoints"], errors="coerce").fillna(0.0)
        history = snapshots.groupby("date", as_index=False).agg(scope=("story_points", "sum"))
        remaining = snapshots.loc[~snapshots["IsDone"].fillna(False)].groupby("date", as_index=False).agg(remaining=("story_points", "sum"))
        return history.merge(remaining, on="date", how="left").fillna({"remaining": 0.0}).to_dict("records")

    def completed_iterations(self, project: str, limit: int = 50) -> list[dict[str, object]]:
        """Return ended Analytics iterations ordered oldest to newest for metric windows."""
        response = self._analytics_request(
            project,
            "Iterations",
            {"$select": "IterationName,StartDate,EndDate,IsEnded", "$filter": "IsEnded eq true", "$orderby": "EndDate desc", "$top": str(limit)},
        )
        iterations = [
            {"name": item["IterationName"], "start": self._date(item.get("StartDate")), "end": self._date(item.get("EndDate"))}
            for item in response.get("value", [])
            if item.get("IterationName") and item.get("StartDate") and item.get("EndDate")
        ]
        return list(reversed(iterations))

    def analytics_velocity_baselines(self, project: str, iterations: list[str], scope: dict[str, tuple[str, ...]] | None = None) -> dict[str, float]:
        """Return scoped first-day Analytics snapshot scope as each sprint's planned baseline."""
        baselines: dict[str, float] = {}
        for iteration in iterations:
            history = self.analytics_burndown_history(project, iteration, scope=scope)
            if history:
                baselines[iteration] = float(history[0]["scope"])
        return baselines

    def analytics_available(self, project: str) -> bool:
        """Check whether the Analytics OData feed is reachable for a project."""
        self._analytics_request(project, "WorkItems", {"$top": "1", "$select": "WorkItemId"})
        return True

    def analytics_work_items(self, project: str) -> list[WorkItem]:
        """Retrieve work items through Azure DevOps Analytics OData as reporting source."""
        fields = "WorkItemId,Title,WorkItemType,State,StateCategory,TagNames,StoryPoints,RemainingWork,CreatedDate,ActivatedDate,ClosedDate,CompletedDate,ChangedDate,LeadTimeDays,CycleTimeDays"
        response = self._analytics_request(
            project,
            "WorkItems",
            {
                "$select": fields,
                "$expand": "Project($select=ProjectName),Area($select=AreaPath),Iteration($select=IterationPath),AssignedTo($select=UserName)",
                "$orderby": "ChangedDate desc",
                "$top": "10000",
            },
        )
        changed_after = datetime.now(timezone.utc).date() - pd.Timedelta(days=self.settings.reporting_lookback_days)
        records = [item for item in response.get("value", []) if self._date(item.get("ChangedDate")) and self._date(item["ChangedDate"]) >= changed_after]
        iteration_windows = [(item["name"], item["start"], item["end"]) for item in self.completed_iterations(project)]
        return [self._normalize_analytics(item, project, iteration_windows) for item in records]

    @staticmethod
    def _date(value: str | None) -> date | None:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date() if value else None

    def _normalize(self, item: dict[str, Any], team: str, state_categories: dict[tuple[str, str], str], iteration_windows: list[tuple[str, date, date]]) -> WorkItem:
        fields = item["fields"]
        assignee = fields.get("System.AssignedTo", {})
        completed = fields.get("Microsoft.VSTS.Common.ClosedDate") or fields.get("Microsoft.VSTS.Common.ResolvedDate")
        item_type = fields.get("System.WorkItemType", "Unknown")
        state = fields.get("System.State", "Unknown")
        iteration = fields.get("System.IterationPath", "Unassigned").split("\\")[-1]
        completed_date = self._date(completed)
        completion_iteration = next((name for name, start, end in iteration_windows if completed_date and start <= completed_date <= end), None)
        assigned_window = next(((start, end) for name, start, end in iteration_windows if name == iteration), (None, None))
        return WorkItem(
            id=item["id"], title=fields.get("System.Title", "Untitled"), project=fields.get("System.TeamProject", ""),
            team=team, iteration=iteration,
            work_item_type=item_type, state=state, state_category=state_categories.get((item_type, state), ""),
            assignee=assignee.get("displayName", "Unassigned") if isinstance(assignee, dict) else str(assignee or "Unassigned"),
            area_path=fields.get("System.AreaPath", "Unassigned"),
            tags=tuple(tag.strip() for tag in fields.get("System.Tags", "").split(";") if tag.strip()),
            story_points=float(fields.get("Microsoft.VSTS.Scheduling.StoryPoints") or 0),
            remaining_work=float(fields.get("Microsoft.VSTS.Scheduling.RemainingWork") or 0),
            created_date=self._date(fields.get("System.CreatedDate")) or date.today(),
            in_progress_date=self._date(fields.get("Microsoft.VSTS.Common.ActivatedDate")),
            completed_date=completed_date, iteration_start=assigned_window[0], iteration_end=assigned_window[1], completion_iteration=completion_iteration,
            reported_lead_time_days=None, reported_cycle_time_days=None,
        )

    def _normalize_analytics(self, item: dict[str, Any], team: str, iteration_windows: list[tuple[str, date, date]]) -> WorkItem:
        """Normalize OData names without exposing transport details to metrics."""
        project_record = item.get("Project") or {}
        area_record = item.get("Area") or {}
        iteration_record = item.get("Iteration") or {}
        assignee_record = item.get("AssignedTo") or {}
        project_name = project_record.get("ProjectName", "")
        area_path = area_record.get("AreaPath", "Unassigned")
        iteration = str(iteration_record.get("IterationPath", "Unassigned")).split("\\")[-1]
        assignee = assignee_record.get("UserName", "Unassigned")
        completed_date = self._date(item.get("CompletedDate") or item.get("ClosedDate"))
        assigned_window = next(((start, end) for name, start, end in iteration_windows if name == iteration), (None, None))
        completion_iteration = next((name for name, start, end in iteration_windows if completed_date and start <= completed_date <= end), None)
        return WorkItem(
            id=int(item["WorkItemId"]), title=item.get("Title", "Untitled"), project=project_name,
            team=team, iteration=iteration,
            work_item_type=item.get("WorkItemType", "Unknown"), state=item.get("State", "Unknown"), state_category=item.get("StateCategory", ""),
            assignee=assignee or "Unassigned", area_path=area_path,
            tags=tuple(tag.strip() for tag in str(item.get("TagNames", "")).split(";") if tag.strip()),
            story_points=float(item.get("StoryPoints") or 0), remaining_work=float(item.get("RemainingWork") or 0),
            created_date=self._date(item.get("CreatedDate")) or date.today(),
            in_progress_date=self._date(item.get("ActivatedDate")), completed_date=completed_date,
            iteration_start=assigned_window[0], iteration_end=assigned_window[1], completion_iteration=completion_iteration,
            reported_lead_time_days=float(item["LeadTimeDays"]) if item.get("LeadTimeDays") is not None else None,
            reported_cycle_time_days=float(item["CycleTimeDays"]) if item.get("CycleTimeDays") is not None else None,
        )


@dataclass(frozen=True)
class Discovery:
    """Project filter catalog supplied by Azure DevOps."""

    teams: list[str]
    iterations: list[str]
    areas: list[str]
    work_item_types: list[str]
    tags: list[str]


def _classification_names(node: dict[str, Any]) -> list[str]:
    """Flatten an Azure classification hierarchy into selectable path names."""
    names = [node.get("name", "")]
    for child in node.get("children", []):
        names.extend(_classification_names(child))
    return [name for name in names if name]


def _classification_windows(node: dict[str, Any]) -> list[tuple[str, date, date]]:
    """Flatten iteration-node start and finish dates into sprint windows."""
    attributes = node.get("attributes", {})
    windows: list[tuple[str, date, date]] = []
    if node.get("name") and attributes.get("startDate") and attributes.get("finishDate"):
        windows.append((node["name"], AzureDevOpsClient._date(attributes["startDate"]), AzureDevOpsClient._date(attributes["finishDate"])))
    for child in node.get("children", []):
        windows.extend(_classification_windows(child))
    return windows


def _revision_at_day_end(revisions: list[dict[str, Any]], day_end: datetime) -> dict[str, Any] | None:
    """Return the latest revision available at the end of a UTC calendar day."""
    latest: dict[str, Any] | None = None
    for revision in revisions:
        changed = datetime.fromisoformat(revision["fields"]["System.ChangedDate"].replace("Z", "+00:00"))
        if changed <= day_end:
            latest = revision
        else:
            break
    return latest
