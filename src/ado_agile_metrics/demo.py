"""Deterministic records for exploring the dashboard before connecting Azure DevOps."""

from datetime import date, timedelta

from .models import WorkItem


def sample_work_items() -> list[WorkItem]:
    """Return a compact cross-sprint dataset with realistic delivery variation."""
    iterations = [
        ("Sprint 21", date(2026, 7, 6), date(2026, 7, 17)),
        ("Sprint 22", date(2026, 7, 20), date(2026, 7, 31)),
        ("Sprint 23", date(2026, 8, 3), date(2026, 8, 14)),
    ]
    specifications = [
        ("User Story", "Closed", "Maya Patel", 5, "Payments", ("Customer",)),
        ("User Story", "Closed", "Jon Bell", 8, "Checkout", ("Priority",)),
        ("Bug", "Closed", "Maya Patel", 3, "Payments", ("Quality",)),
        ("Task", "Active", "Lina Chen", 2, "Platform", ("Infrastructure",)),
        ("Feature", "Resolved", "Jon Bell", 13, "Checkout", ("Customer", "Priority")),
        ("User Story", "New", "Lina Chen", 5, "Platform", ("Discovery",)),
    ]
    work_items: list[WorkItem] = []
    for sprint_index, (iteration, start, end) in enumerate(iterations):
        for item_index, (item_type, state, assignee, points, area, tags) in enumerate(specifications):
            completed = start + timedelta(days=3 + item_index) if state in {"Closed", "Resolved"} else None
            if sprint_index == 2 and item_index == 4:
                completed = None
                state = "Active"
            work_items.append(
                WorkItem(
                    id=1000 + sprint_index * 10 + item_index,
                    title=f"{item_type} {item_index + 1} for {iteration}",
                    project="Demo Commerce",
                    team="Product Engineering",
                    iteration=iteration,
                    work_item_type=item_type,
                    state=state,
                    state_category="Completed" if completed else "InProgress",
                    assignee=assignee,
                    area_path=area,
                    tags=tags,
                    story_points=float(points),
                    remaining_work=0.0 if completed else float(points),
                    created_date=start - timedelta(days=7 + item_index),
                    in_progress_date=start + timedelta(days=1 + item_index),
                    completed_date=completed,
                    iteration_start=start,
                    iteration_end=end,
                    completion_iteration=iteration if completed else None,
                    reported_lead_time_days=None,
                    reported_cycle_time_days=None,
                )
            )
    return work_items