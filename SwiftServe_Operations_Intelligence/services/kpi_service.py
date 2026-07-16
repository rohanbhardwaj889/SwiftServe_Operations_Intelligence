import os
import sys

# Allow this file to be run directly (python services/kpi_service.py or the
# VS Code Run button) as well as with -m. Running a file directly only puts
# its own folder on sys.path, not the project root, so "services" isn't
# importable as a package -- this adds the project root manually.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from services.data_service import (
    get_work_orders,
    get_technicians,
    get_equipment,
    get_dispatch_logs,
    get_sla_metrics,
)


# ---------------------------------------------------------------------
# ASK: how many jobs are still unresolved right now?
# ANSWER: count of work orders whose status isn't "Completed"
# ---------------------------------------------------------------------
def kpi_open_tickets(work_orders: pd.DataFrame) -> dict:
    open_df = work_orders[work_orders["status"] != "Completed"]
    return {
        "count": len(open_df),
        "by_status": open_df["status"].value_counts().to_dict(),
        "ticket_ids": open_df["work_order_id"].tolist(),
    }


# ---------------------------------------------------------------------
# ASK: which open tickets are close to, or already past, their
#      SLA resolution window?
# ANSWER: BREACHED / AT_RISK / ON_TRACK flag per open ticket.
#
# Joined on customer_name, since that's the only shared key between
# work_orders and sla_metrics in this dataset (not every work order's
# customer has a matching SLA record -> flagged as NO_SLA_DATA, not dropped)
# ---------------------------------------------------------------------
def kpi_tickets_at_risk(work_orders: pd.DataFrame, sla_metrics: pd.DataFrame,
                         as_of_date=None, at_risk_threshold=0.8) -> pd.DataFrame:
    work_orders = work_orders.copy()
    for col in ["created_date", "due_date", "completed_date"]:
        work_orders[col] = pd.to_datetime(work_orders[col], errors="coerce")

    if as_of_date is None:
        as_of_date = work_orders["due_date"].max()

    open_df = work_orders[work_orders["status"] != "Completed"].copy()

    merged = open_df.merge(
        sla_metrics[["customer_name", "resolution_time_target_hours"]],
        on="customer_name", how="left"
    )

    merged["elapsed_hours"] = (as_of_date - merged["created_date"]).dt.total_seconds() / 3600
    # Separate from the SLA-target risk flag below: this is a direct
    # "is it past its contractual due_date" check, since ACT mode asks
    # for overdue-by-due_date specifically, not just SLA-window risk.
    merged["is_overdue"] = merged["due_date"] < as_of_date

    def flag(row):
        if pd.isna(row["resolution_time_target_hours"]):
            return "NO_SLA_DATA"
        if row["elapsed_hours"] > row["resolution_time_target_hours"]:
            return "BREACHED"
        if row["elapsed_hours"] > at_risk_threshold * row["resolution_time_target_hours"]:
            return "AT_RISK"
        return "ON_TRACK"

    merged["risk_flag"] = merged.apply(flag, axis=1)

    return merged[["work_order_id", "customer_name", "location", "priority",
                    "due_date", "is_overdue", "elapsed_hours",
                    "resolution_time_target_hours", "risk_flag"]]


# ---------------------------------------------------------------------
# ASK: are we honoring our SLA contracts this month?
# ANSWER: compliance % per customer, plus who's below a safe threshold
# ---------------------------------------------------------------------
def kpi_sla_compliance(sla_metrics: pd.DataFrame, breach_threshold=95) -> dict:
    at_risk_customers = sla_metrics[sla_metrics["sla_compliance_percent"] < breach_threshold]
    all_customers = sla_metrics[
        ["customer_name", "sla_tier", "sla_compliance_percent",
         "sla_breaches_this_month", "actual_uptime_percent"]
    ].sort_values("sla_compliance_percent")

    return {
        "overall_avg_compliance_percent": round(sla_metrics["sla_compliance_percent"].mean(), 1),
        "customers_below_threshold": at_risk_customers[
            ["customer_name", "sla_tier", "sla_compliance_percent", "sla_breaches_this_month"]
        ].to_dict(orient="records"),
        "all_customers": all_customers,
    }


# ---------------------------------------------------------------------
# ASK: could a repair get blocked tomorrow due to equipment risk?
# ANSWER: equipment with multiple unresolved critical alerts, or
#         already Degraded/Inactive (closest proxy -- no inventory table)
# ---------------------------------------------------------------------
def kpi_critical_equipment(equipment: pd.DataFrame, alert_threshold=2) -> pd.DataFrame:
    critical = equipment[
        (equipment["critical_alerts"] > alert_threshold) |
        (equipment["status"].isin(["Degraded", "Inactive"]))
    ]
    return critical[["equipment_id", "customer_id", "equipment_name",
                      "status", "critical_alerts"]]


# ---------------------------------------------------------------------
# ASK: how is each technician performing?
# ANSWER: completion rate + avg response time, ranked
# ---------------------------------------------------------------------
def kpi_technician_performance(technicians: pd.DataFrame) -> pd.DataFrame:
    df = technicians.copy()
    df["completion_rate_percent"] = (
        df["completed_assignments"] / df["total_assignments"] * 100
    ).round(1)

    return df[["technician_id", "name", "location", "status", "skills",
               "total_assignments", "completion_rate_percent", "avg_response_time_hours"]] \
        .sort_values("completion_rate_percent", ascending=False)


# ---------------------------------------------------------------------
# ASK: how is the field actually performing -- how fast do techs show
#      up, and are customers happy once the job is done?
# ANSWER: avg dispatch-to-arrival time, avg customer feedback rating,
#         and a breakdown of dispatch statuses.
# ---------------------------------------------------------------------
def kpi_dispatch_performance(dispatch_logs: pd.DataFrame) -> dict:
    df = dispatch_logs.copy()
    df["dispatch_time"] = pd.to_datetime(df["dispatch_time"], errors="coerce")
    df["arrival_time"] = pd.to_datetime(df["arrival_time"], errors="coerce")

    response_hours = (df["arrival_time"] - df["dispatch_time"]).dt.total_seconds() / 3600
    feedback = pd.to_numeric(df["customer_feedback_rating"], errors="coerce")

    return {
        "average_response_time_hours": round(response_hours.mean(skipna=True), 2),
        "average_customer_feedback": round(feedback.mean(skipna=True), 2),
        "dispatch_status_breakdown": df["status"].value_counts().to_dict(),
    }


# ---------------------------------------------------------------------
# ASK: how much billed money is overdue?
# ANSWER: not computable -- no invoices table exists in this database.
# Kept as a real function (not silently skipped) so the gap is visible
# in the output rather than hidden.
# ---------------------------------------------------------------------
def kpi_overdue_invoices() -> dict:
    return {"status": "NOT_AVAILABLE", "reason": "no invoices table exists in SwiftServeDB"}


# ---------------------------------------------------------------------
# ASK: which zone has the most open/overdue tickets?
# ANSWER: group work_orders by location
# ---------------------------------------------------------------------
def kpi_zone_summary(work_orders: pd.DataFrame, as_of_date=None) -> pd.DataFrame:
    df = work_orders.copy()
    for col in ["created_date", "due_date", "completed_date"]:
        df[col] = pd.to_datetime(df[col], errors="coerce")

    if as_of_date is None:
        as_of_date = df["due_date"].max()

    df["is_open"] = df["status"] != "Completed"
    df["is_overdue"] = df["is_open"] & (df["due_date"] < as_of_date)

    summary = df.groupby("location").agg(
        open_tickets=("is_open", "sum"),
        overdue_tickets=("is_overdue", "sum"),
        total_tickets=("work_order_id", "count"),
    ).sort_values("overdue_tickets", ascending=False)

    return summary.reset_index()


# ---------------------------------------------------------------------
# ASK (EXPLORE): which assets are heading into a maintenance window soon,
#      before they become a critical/degraded risk?
# ANSWER: equipment whose next_maintenance_due has already passed, or
#         falls within `due_soon_days` of the latest known activity in
#         the dataset. last_maintenance.max() stands in for "today"
#         since this is a fixed historical demo dataset, not a live feed.
# ---------------------------------------------------------------------
def kpi_maintenance_due(equipment: pd.DataFrame, as_of_date=None, due_soon_days=30) -> pd.DataFrame:
    df = equipment.copy()
    for col in ["last_maintenance", "next_maintenance_due"]:
        df[col] = pd.to_datetime(df[col], errors="coerce")

    if as_of_date is None:
        as_of_date = df["last_maintenance"].max()

    df["days_until_due"] = (df["next_maintenance_due"] - as_of_date).dt.days

    def flag(days):
        if pd.isna(days):
            return "NO_SCHEDULE"
        if days < 0:
            return "OVERDUE"
        if days <= due_soon_days:
            return "DUE_SOON"
        return "SCHEDULED"

    df["maintenance_status"] = df["days_until_due"].apply(flag)

    upcoming = df[df["maintenance_status"].isin(["OVERDUE", "DUE_SOON"])]
    return upcoming[["equipment_id", "equipment_name", "location", "status",
                      "next_maintenance_due", "days_until_due", "maintenance_status"]] \
        .sort_values("days_until_due")


# ---------------------------------------------------------------------
# ASK (EXPLORE): for open work, which available technician is the best
#      fit -- matching the job's issue_type against each active
#      technician's listed skills?
# ANSWER: a deterministic skill-keyword match per open work order,
#         ranked by the technician's completion rate. Falls back to
#         "best available technician in that location" if no skill
#         keyword matches, since not every issue_type has a clean
#         one-word skill equivalent in this dataset.
# ---------------------------------------------------------------------
_ISSUE_SKILL_MAP = {
    "Equipment Failure": ["Repairs", "Diagnostics"],
    "Maintenance Check": ["Maintenance"],
    "Preventive Maintenance": ["Preventive Maintenance", "Maintenance"],
    "Installation": ["Installation"],
    "Troubleshooting": ["Troubleshooting", "Diagnostics"],
    "Emergency Repair": ["Repairs"],
    "Equipment Diagnostics": ["Diagnostics"],
}


def kpi_skill_match(work_orders: pd.DataFrame, technicians: pd.DataFrame) -> pd.DataFrame:
    open_df = work_orders[work_orders["status"] != "Completed"].copy()
    active_techs = technicians[technicians["status"] == "Active"].copy()
    active_techs["completion_rate_percent"] = (
        active_techs["completed_assignments"] / active_techs["total_assignments"] * 100
    ).round(1)

    rows = []
    for _, ticket in open_df.iterrows():
        keywords = _ISSUE_SKILL_MAP.get(ticket["issue_type"], [])
        candidates = (
            active_techs[active_techs["skills"].apply(lambda s: any(k in s for k in keywords))]
            if keywords else active_techs.iloc[0:0]
        )

        match_basis = "Skill match"
        if candidates.empty:
            candidates = active_techs[active_techs["location"] == ticket["location"]]
            match_basis = "Location match" if not candidates.empty else "No candidate available"

        if not candidates.empty:
            best = candidates.sort_values("completion_rate_percent", ascending=False).iloc[0]
            recommended, completion_rate = best["name"], best["completion_rate_percent"]
        else:
            recommended, completion_rate = "N/A", None

        rows.append({
            "work_order_id": ticket["work_order_id"],
            "issue_type": ticket["issue_type"],
            "location": ticket["location"],
            "current_technician": ticket["assigned_technician"],
            "recommended_technician": recommended,
            "match_basis": match_basis,
            "recommended_completion_rate": completion_rate,
        })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------
# ASK (OBSERVE): is resolution time getting faster or slower over time?
# ANSWER: average resolution time for completed work orders, grouped by
#         the date each work order was created.
# ---------------------------------------------------------------------
def kpi_cycle_time_trends(work_orders: pd.DataFrame) -> pd.DataFrame:
    df = work_orders.copy()
    df["created_date"] = pd.to_datetime(df["created_date"], errors="coerce")
    completed = df[df["status"] == "Completed"].copy()
    completed["resolution_time_hours"] = pd.to_numeric(
        completed["resolution_time_hours"], errors="coerce"
    )

    trend = completed.groupby(completed["created_date"].dt.date).agg(
        avg_resolution_time_hours=("resolution_time_hours", "mean"),
        completed_count=("work_order_id", "count"),
    ).reset_index().rename(columns={"created_date": "date"})

    return trend.sort_values("date")


# ---------------------------------------------------------------------
# ASK (EXPLORE): what's actually slowing resolution down -- a particular
#      issue type, rather than a particular zone?
# ANSWER: average resolution time and open/overdue counts grouped by
#         issue_type, ranked so the slowest category surfaces first.
# ---------------------------------------------------------------------
def kpi_bottleneck_analysis(work_orders: pd.DataFrame, as_of_date=None) -> pd.DataFrame:
    df = work_orders.copy()
    for col in ["created_date", "due_date"]:
        df[col] = pd.to_datetime(df[col], errors="coerce")
    df["resolution_time_hours"] = pd.to_numeric(df["resolution_time_hours"], errors="coerce")

    if as_of_date is None:
        as_of_date = df["due_date"].max()

    df["is_open"] = df["status"] != "Completed"
    df["is_overdue"] = df["is_open"] & (df["due_date"] < as_of_date)

    summary = df.groupby("issue_type").agg(
        avg_resolution_time_hours=("resolution_time_hours", "mean"),
        open_count=("is_open", "sum"),
        overdue_count=("is_overdue", "sum"),
        total_count=("work_order_id", "count"),
    ).reset_index()

    return summary.sort_values("avg_resolution_time_hours", ascending=False, na_position="last")


# ---------------------------------------------------------------------
# Orchestrator -- pulls every KPI into one summary dict, live from SQL Server
# ---------------------------------------------------------------------
def build_kpi_summary() -> dict:
    work_orders = get_work_orders()
    technicians = get_technicians()
    equipment = get_equipment()
    sla_metrics = get_sla_metrics()
    dispatch_logs = get_dispatch_logs()

    return {
        "open_tickets": kpi_open_tickets(work_orders),
        "tickets_at_risk": kpi_tickets_at_risk(work_orders, sla_metrics),
        "sla_compliance": kpi_sla_compliance(sla_metrics),
        "critical_equipment": kpi_critical_equipment(equipment),
        "technician_performance": kpi_technician_performance(technicians),
        "dispatch_performance": kpi_dispatch_performance(dispatch_logs),
        "overdue_invoices": kpi_overdue_invoices(),
        "zone_summary": kpi_zone_summary(work_orders),
        "maintenance_due": kpi_maintenance_due(equipment),
        "skill_match": kpi_skill_match(work_orders, technicians),
        "cycle_time_trends": kpi_cycle_time_trends(work_orders),
        "bottleneck_analysis": kpi_bottleneck_analysis(work_orders),
    }


if __name__ == "__main__":
    summary = build_kpi_summary()

    print("\n=== OPEN TICKETS ===")
    print(summary["open_tickets"])

    print("\n=== TICKETS AT RISK ===")
    print(summary["tickets_at_risk"].to_string(index=False))

    print("\n=== SLA COMPLIANCE ===")
    print(summary["sla_compliance"])

    print("\n=== CRITICAL EQUIPMENT ===")
    print(summary["critical_equipment"].to_string(index=False))

    print("\n=== TECHNICIAN PERFORMANCE ===")
    print(summary["technician_performance"].to_string(index=False))

    print("\n=== DISPATCH PERFORMANCE ===")
    print(summary["dispatch_performance"])

    print("\n=== OVERDUE INVOICES ===")
    print(summary["overdue_invoices"])

    print("\n=== ZONE SUMMARY ===")
    print(summary["zone_summary"].to_string(index=False))

    print("\n=== MAINTENANCE DUE ===")
    print(summary["maintenance_due"].to_string(index=False))

    print("\n=== SKILL MATCH ===")
    print(summary["skill_match"].to_string(index=False))

    print("\n=== CYCLE TIME TRENDS ===")
    print(summary["cycle_time_trends"].to_string(index=False))

    print("\n=== BOTTLENECK ANALYSIS ===")
    print(summary["bottleneck_analysis"].to_string(index=False))
