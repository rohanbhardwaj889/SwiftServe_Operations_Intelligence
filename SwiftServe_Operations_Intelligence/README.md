# SwiftServe Operations Intelligence

SwiftServe Operations Intelligence is a field-service control tower for operations managers. It combines live SQL Server data, operational KPIs, a premium Streamlit dashboard, rule-based recommendations, and an optional Gemini-powered AI Morning Brief.

## What it helps an operations manager decide

| Dashboard area | Question it answers |
|---|---|
| Priority Queue | Which open work orders require action first? |
| SLA Risk | Which customer commitments are breached or approaching breach? |
| Operational Load by Location | Where should dispatch capacity or technicians be focused? |
| Customer Confidence | Which customer accounts have the lowest SLA compliance? |
| Equipment Watchlist | Which assets are degraded, inactive, or carrying critical alerts? |
| Recommendation Engine | What is the most useful next operational action? |
| AI Morning Brief | What should leadership know at the start of the day? |

## Features

- Live SQL Server data for work orders, technicians, equipment, dispatch logs, and SLA metrics
- Open-ticket, SLA-risk, customer-compliance, equipment-risk, technician-performance, dispatch, and zone KPIs
- Search, location, priority, and SLA-status filters
- Work-order drill-down
- Auto-refresh option every five minutes
- CSV priority-queue export and executive PDF export
- Clear system-health status for SQL, Gemini, and refresh configuration
- Deterministic recommendation engine
- Optional Gemini AI Morning Brief with actionable error messages

## Project structure

```text
SwiftServe_Operations_Intelligence/
|-- app.py                         # Streamlit dashboard
|-- requirements.txt               # Python packages
|-- .env                           # Local configuration; never commit
|-- services/
|   |-- database.py                # SQL Server connection using .env
|   |-- data_service.py            # Queries for all five datasets
|   |-- kpi_service.py             # KPI calculations and summary builder
|   `-- ai_brief_service.py        # Gemini briefing and diagnostics
```

## Prerequisites

- Python with a project virtual environment in `.venv`
- SQL Server / SQL Server Express running locally
- ODBC Driver 18 for SQL Server
- A database named `SwiftServeDB` containing:
  - `swiftserve_work_orders`
  - `swiftserve_technicians`
  - `swiftserve_equipment`
  - `swiftserve_dispatch_logs`
  - `swiftserve_sla_metrics`
- Optional: a Gemini API key for AI Morning Briefs

## 1. Configure `.env`

Create a file named `.env` in the project root. The project already ignores this file in Git.

```env
# SQL Server connection
DB_SERVER=ROHAN\SQLEXPRESS
DB_DATABASE=SwiftServeDB
DB_DRIVER=ODBC Driver 18 for SQL Server

# Gemini AI Morning Brief (optional)
GEMINI_API_KEY=your_actual_api_key
GEMINI_MODEL=gemini-3.5-flash
```

Replace `DB_SERVER` with your own SQL Server instance if required. Do not put credentials or API keys directly in Python files.

## 2. Install dependencies

From the project root, activate the virtual environment:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install all packages:

```powershell
python -m pip install -r requirements.txt
```

If the dashboard says a Gemini, PDF, or auto-refresh package is missing, install only those packages:

```powershell
.\.venv\Scripts\python.exe -m pip install google-genai streamlit-autorefresh reportlab
```

## 3. Test the data layer

Test the SQL Server connection:

```powershell
.\.venv\Scripts\python.exe -m services.database
```

Preview the data returned from the five database tables:

```powershell
.\.venv\Scripts\python.exe -m services.data_service
```

Run the KPI service in the terminal:

```powershell
.\.venv\Scripts\python.exe -m services.kpi_service
```

> Always run package modules from the project root with `-m services...`. This ensures imports such as `from services.data_service import ...` work correctly.

## 4. Test the AI Morning Brief

Check the configuration first:

```powershell
.\.venv\Scripts\python.exe -c "from services.ai_brief_service import get_ai_status; print(get_ai_status())"
```

Expected successful result:

```text
{'ready': True, 'label': 'Gemini ready', 'message': 'Model: gemini-3.5-flash'}
```

Generate a test briefing:

```powershell
.\.venv\Scripts\python.exe -c "from services.kpi_service import build_kpi_summary; from services.ai_brief_service import generate_morning_brief; summary = build_kpi_summary(); print(generate_morning_brief(summary, summary['tickets_at_risk'], summary['critical_equipment']))"
```

The dashboard sends operational context to Gemini only when **Generate AI morning brief** is clicked.

## 5. Run the dashboard

```powershell
.\.venv\Scripts\streamlit.exe run app.py
```

Open the URL Streamlit displays, usually:

```text
http://localhost:8501
```

To restart the app, press `Ctrl + C` in the terminal and run the same command again.

## KPI logic

- **Open tickets**: work orders whose status is not `Completed`.
- **SLA risk**: compares elapsed work-order time to each customer's resolution target. Records without matching SLA data are marked `NO_SLA_DATA`.
- **SLA compliance**: ranks customer accounts by `sla_compliance_percent`; the dashboard flags customers below 90%.
- **Critical equipment**: includes degraded/inactive equipment or assets with more than two critical alerts.
- **Technician performance**: calculates completion rate from completed assignments divided by total assignments.
- **Dispatch performance**: measures dispatch-to-arrival time and customer feedback.
- **Zone summary**: compares open and overdue work orders by location.

## Troubleshooting

| Problem | What to do |
|---|---|
| `ModuleNotFoundError: No module named 'services'` | Run from the project root with `.\.venv\Scripts\python.exe -m services.kpi_service`. |
| SQL connection fails | Check `.env`, confirm SQL Server is running, verify `DB_SERVER`, and ensure ODBC Driver 18 is installed. |
| Dashboard says `API key needed` | Add `GEMINI_API_KEY` to `.env`, save it, and restart Streamlit. |
| Dashboard says `Gemini SDK missing` | Run `.\.venv\Scripts\python.exe -m pip install google-genai`. |
| Gemini rejects the key | Generate or verify a valid Gemini key, update `.env`, and restart Streamlit. |
| PDF export unavailable | Run `.\.venv\Scripts\python.exe -m pip install reportlab`. |
| Auto-refresh unavailable | Run `.\.venv\Scripts\python.exe -m pip install streamlit-autorefresh`. |
| Charts show small values | The current sample dataset has few work orders per location; larger operational data makes the location chart more informative. |

## Security and privacy

- `.env` contains local secrets and must never be committed to Git.
- The Gemini API key is not displayed in the dashboard or stored in source code.
- The AI Morning Brief is requested manually; it does not run automatically on every dashboard refresh.
