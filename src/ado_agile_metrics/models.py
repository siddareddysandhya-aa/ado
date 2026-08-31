"""Domain records shared by Azure and demo data sources."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class WorkItem:
    """Normalized work item used by metric calculations."""

    id: int
    title: str
    project: str
    team: str
    iteration: str
    work_item_type: str
    state: str
    state_category: str
    assignee: str
    area_path: str
    tags: tuple[str, ...]
    story_points: float
    remaining_work: float
    created_date: date
    in_progress_date: date | None
    completed_date: date | None
    iteration_start: date | None
    iteration_end: date | None
    completion_iteration: str | None
    reported_lead_time_days: float | None = None
    reported_cycle_time_days: float | None = None
