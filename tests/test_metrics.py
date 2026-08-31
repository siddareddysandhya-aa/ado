from ado_agile_metrics.demo import sample_work_items
from ado_agile_metrics.metrics import executive_insights, flow_time_percentiles, kpis, to_frame, velocity_by_iteration, velocity_report
import pandas as pd


def test_velocity_and_kpis_use_completed_work_only():
    frame = to_frame(sample_work_items())

    velocity = velocity_by_iteration(frame)
    values = kpis(frame)

    assert len(velocity) == 3
    assert (velocity["completed_story_points"] <= velocity["planned_story_points"]).all()
    assert values["throughput"] > 0
    assert values["velocity"] > 0


def test_executive_insights_returns_delivery_observations():
    insights = executive_insights(to_frame(sample_work_items()))

    assert len(insights) >= 2
    assert any("committed" in insight for insight in insights)


def test_configured_accepted_state_is_completed():
    item = sample_work_items()[0]
    accepted_item = item.__class__(**{**item.__dict__, "state": "Accepted", "state_category": ""})

    frame = to_frame([accepted_item], completed_states=("Accepted",))

    assert frame["is_done"].iloc[0]


def test_flow_time_summary_uses_completed_date_window():
    frame = to_frame(sample_work_items())
    cutoff = frame["completed_date"].max() - pd.Timedelta(days=1)

    summary = flow_time_percentiles(frame, "lead_time_days", cutoff)

    assert summary["average"] > 0


def test_flow_time_summary_honors_completion_end_date():
    frame = to_frame(sample_work_items())
    before_all_completions = frame["completed_date"].min()

    summary = flow_time_percentiles(frame, "lead_time_days", completed_before=before_all_completions)

    assert summary["average"] > 0


def test_analytics_flow_durations_override_date_subtraction():
    item = sample_work_items()[0]
    analytics_item = item.__class__(**{**item.__dict__, "reported_lead_time_days": 14.5, "reported_cycle_time_days": 8.5})

    frame = to_frame([analytics_item])

    assert frame["lead_time_days"].iloc[0] == 14.5
    assert frame["cycle_time_days"].iloc[0] == 8.5


def test_completed_date_drives_velocity_sprint_credit():
    item = sample_work_items()[0]
    completed_item = item.__class__(**{**item.__dict__, "state": "Accepted", "state_category": "Completed", "completion_iteration": "Sprint 21"})

    report = velocity_report(to_frame([completed_item]))

    assert report.loc[report["iteration"] == "Sprint 21", "Completed"].iloc[0] == completed_item.story_points


def test_velocity_report_has_azure_style_categories():
    report = velocity_report(to_frame(sample_work_items()))

    assert {"Planned", "Completed", "Completed Late", "Incomplete"}.issubset(report.columns)
    assert report["Planned"].sum() > 0
    assert report["Completed"].sum() > 0


def test_velocity_report_counts_work_completed_after_its_assigned_sprint_as_late():
    item = sample_work_items()[0]
    late_item = item.__class__(**{**item.__dict__, "completed_date": item.iteration_end + __import__("datetime").timedelta(days=1), "completion_iteration": item.iteration})

    report = velocity_report(to_frame([late_item]))

    assert report["Completed Late"].iloc[0] == late_item.story_points


def test_velocity_report_uses_historical_planned_baseline_when_provided():
    frame = to_frame(sample_work_items())

    report = velocity_report(frame, planned_baselines={"Sprint 21": 99.0})

    assert report.loc[report["iteration"] == "Sprint 21", "Planned"].iloc[0] == 99.0