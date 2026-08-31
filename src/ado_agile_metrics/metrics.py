"""Metric computations over normalized Azure DevOps work items."""

from collections.abc import Iterable

import pandas as pd

from .models import WorkItem


DONE_STATE_CATEGORIES = {"completed"}
DONE_STATES = {"closed", "resolved", "done", "completed"}


def to_frame(work_items: Iterable[WorkItem], completed_states: Iterable[str] = DONE_STATES) -> pd.DataFrame:
    """Convert work items into a dataframe suitable for filtering and charting."""
    records = [{**item.__dict__, "tags": "; ".join(item.tags)} for item in work_items]
    frame = pd.DataFrame(records)
    if frame.empty:
        return frame
    for column in ("created_date", "in_progress_date", "completed_date", "iteration_start", "iteration_end"):
        frame[column] = pd.to_datetime(frame[column])
    configured_states = {state.lower() for state in completed_states}
    frame["is_done"] = frame["state_category"].str.lower().isin(DONE_STATE_CATEGORIES) | frame["state"].str.lower().isin(configured_states)
    calculated_lead_time = (frame["completed_date"] - frame["created_date"]).dt.days
    calculated_cycle_time = (frame["completed_date"] - frame["in_progress_date"]).dt.days
    frame["lead_time_days"] = pd.to_numeric(frame["reported_lead_time_days"], errors="coerce").fillna(calculated_lead_time)
    frame["cycle_time_days"] = pd.to_numeric(frame["reported_cycle_time_days"], errors="coerce").fillna(calculated_cycle_time)
    return frame


def velocity_by_iteration(frame: pd.DataFrame, iterations: list[str] | None = None) -> pd.DataFrame:
    """Calculate planned points by assigned sprint and velocity by completion sprint."""
    selected = set(iterations or frame["iteration"].unique())
    planned = frame[frame["iteration"].isin(selected)].groupby("iteration", as_index=False)["story_points"].sum().rename(columns={"story_points": "planned_story_points"})
    completed = frame[frame["is_done"] & frame["completion_iteration"].isin(selected)].groupby("completion_iteration", as_index=False)["story_points"].sum().rename(columns={"completion_iteration": "iteration", "story_points": "completed_story_points"})
    grouped = planned.merge(completed, on="iteration", how="outer").fillna(0)
    grouped["predictability"] = grouped["completed_story_points"].div(grouped["planned_story_points"].replace(0, pd.NA)) * 100
    return grouped


def velocity_report(frame: pd.DataFrame, iterations: list[str] | None = None, planned_baselines: dict[str, float] | None = None) -> pd.DataFrame:
    """Build Azure DevOps-style planned, completed, late, and incomplete sprint totals."""
    selected = set(iterations or frame["iteration"].dropna().unique())
    planned = frame[frame["iteration"].isin(selected)].groupby("iteration")["story_points"].sum()
    incomplete = frame[frame["iteration"].isin(selected) & frame["state_category"].str.lower().eq("inprogress")].groupby("iteration")["story_points"].sum()
    delivered = frame[frame["is_done"] & frame["completion_iteration"].isin(selected)].copy()
    completed = delivered.groupby("completion_iteration")["story_points"].sum()
    late_items = frame[
        frame["is_done"] & frame["iteration"].isin(selected) & frame["iteration_end"].notna() & frame["completed_date"].notna() & (frame["completed_date"] > frame["iteration_end"])
    ]
    late = late_items.groupby("iteration")["story_points"].sum()
    report = pd.DataFrame(index=sorted(selected))
    report["Planned"] = planned
    report["Completed"] = completed
    report["Completed Late"] = late
    report["Incomplete"] = incomplete
    report = report.fillna(0).rename_axis("iteration").reset_index()
    if planned_baselines:
        report["Planned"] = report["iteration"].map(planned_baselines).fillna(report["Planned"])
    return report


def kpis(frame: pd.DataFrame) -> dict[str, float]:
    """Return executive KPI values for the filtered selection."""
    velocity = velocity_by_iteration(frame)
    done = frame[frame["is_done"]]
    return {
        "velocity": float(velocity["completed_story_points"].mean() if not velocity.empty else 0),
        "predictability": float(velocity["predictability"].mean() if not velocity.empty else 0),
        "lead_time": float(done["lead_time_days"].mean() if not done.empty else 0),
        "cycle_time": float(done["cycle_time_days"].mean() if not done.empty else 0),
        "throughput": float(len(done)),
    }


def flow_time_percentiles(frame: pd.DataFrame, column: str, completed_after: pd.Timestamp | None = None, completed_before: pd.Timestamp | None = None) -> dict[str, float]:
    """Return flow-time summaries for completed items within an optional completion window."""
    completed = frame.loc[frame["is_done"]]
    if completed_after is not None:
        completed = completed[completed["completed_date"].ge(completed_after)]
    if completed_before is not None:
        completed = completed[completed["completed_date"].le(completed_before)]
    values = completed[column].dropna()
    if values.empty:
        return {"average": 0.0, "median": 0.0, "p75": 0.0, "p90": 0.0}
    return {"average": float(values.mean()), "median": float(values.median()), "p75": float(values.quantile(0.75)), "p90": float(values.quantile(0.9))}


def executive_insights(frame: pd.DataFrame) -> list[str]:
    """Generate explainable executive observations from current metric values."""
    velocity = velocity_by_iteration(frame)
    insights: list[str] = []
    if len(velocity) >= 2 and velocity.iloc[-2]["completed_story_points"]:
        change = (velocity.iloc[-1]["completed_story_points"] / velocity.iloc[-2]["completed_story_points"] - 1) * 100
        insights.append(f"Velocity {'improved' if change >= 0 else 'declined'} by {abs(change):.0f}% from the previous iteration.")
    if not velocity.empty:
        latest = velocity.iloc[-1]
        insights.append(f"Latest iteration committed {latest.planned_story_points:.0f} SP and delivered {latest.completed_story_points:.0f} SP, producing {latest.predictability:.0f}% predictability.")
    completed = frame[frame["is_done"]]
    if not completed.empty:
        lead_by_type = completed.groupby("work_item_type")["lead_time_days"].mean().sort_values(ascending=False)
        insights.append(f"{lead_by_type.index[0]} work items have the longest average lead time at {lead_by_type.iloc[0]:.1f} days.")
    return insights
