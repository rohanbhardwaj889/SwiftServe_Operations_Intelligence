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
                    "elapsed_hours", "resolution_time_target_hours", "risk_flag"]]


# ---------------------------------------------------------------------
# ASK: are we honoring our SLA contracts this month?
# ANSWER: compliance % per customer, plus who's below a safe threshold
# ---------------------------------------------------------------------
def kpi_sla_compliance(sla_metrics: pd.DataFrame, breach_threshold=90) -> dict:
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