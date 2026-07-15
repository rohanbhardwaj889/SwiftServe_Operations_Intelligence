"""Gemini-powered morning brief service for the SwiftServe dashboard.

Keeping AI integration here makes setup and API failures easy to diagnose without
mixing Gemini code into the Streamlit interface.
"""

import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"
DEFAULT_MODEL = "gemini-3.5-flash"


class MorningBriefError(RuntimeError):
    """An actionable error that can be shown safely in the dashboard."""


def _load_environment() -> None:
    """Load the project's .env file each time status is checked."""
    load_dotenv(ENV_FILE, override=False)


def get_ai_status() -> dict:
    """Return an explicit readiness state for the dashboard health card."""
    _load_environment()
    api_key = os.getenv("GEMINI_API_KEY", "").strip()

    if not ENV_FILE.exists():
        return {
            "ready": False,
            "label": "Missing .env file",
            "message": "Create .env in the project root, then add GEMINI_API_KEY=your_key.",
        }
    if not api_key:
        return {
            "ready": False,
            "label": "API key needed",
            "message": "Add GEMINI_API_KEY=your_key to .env, save it, and restart Streamlit.",
        }

    try:
        from google import genai  # noqa: F401
    except ImportError:
        return {
            "ready": False,
            "label": "Gemini SDK missing",
            "message": "Run: .\\.venv\\Scripts\\python.exe -m pip install google-genai",
        }

    return {
        "ready": True,
        "label": "Gemini ready",
        "message": f"Model: {os.getenv('GEMINI_MODEL', DEFAULT_MODEL)}",
    }


def _build_prompt(summary: dict, risks: pd.DataFrame, equipment: pd.DataFrame) -> str:
    risk_rows = risks.head(5)[
        ["work_order_id", "customer_name", "location", "priority", "risk_flag", "elapsed_hours"]
    ].to_dict(orient="records")
    equipment_rows = equipment.head(5).to_dict(orient="records")
    sla = summary["sla_compliance"]

    return f"""
You are the operations chief of staff for SwiftServe, a field-service company.
Write a concise executive morning brief using only the data supplied below.

Use these exact headings:
1. Situation now
2. Immediate actions
3. Watch items

Rules:
- Be concrete, prioritised, and concise.
- Do not invent facts, dates, technicians, or causes.
- Mention work-order IDs when relevant.
- Limit the response to 220 words.

Operational snapshot:
- Open tickets: {summary['open_tickets']['count']}
- Average SLA compliance: {sla['overall_avg_compliance_percent']}%
- Dispatch average response time: {summary['dispatch_performance']['average_response_time_hours']} hours
- Dispatch average customer feedback: {summary['dispatch_performance']['average_customer_feedback']} / 5
- Tickets at risk: {risk_rows}
- Equipment watchlist: {equipment_rows}
- Customers below SLA threshold: {sla['customers_below_threshold']}
""".strip()


def _friendly_error(error: Exception) -> str:
    text = str(error)
    upper = text.upper()
    if any(token in upper for token in ("API_KEY", "UNAUTHENTICATED", "PERMISSION_DENIED")):
        return "Gemini rejected the API key. Check GEMINI_API_KEY in .env and restart Streamlit."
    if "NOT_FOUND" in upper or "MODEL" in upper:
        return (
            "The configured Gemini model is unavailable to this key. "
            "Check GEMINI_MODEL in .env."
        )
    if any(token in upper for token in ("429", "RESOURCE_EXHAUSTED", "RATE")):
        return "Gemini rate limit reached. Wait a moment, then generate the brief again."
    if any(token in upper for token in ("CONNECTION", "TIMEOUT", "NETWORK")):
        return "Gemini could not be reached. Check your internet connection and try again."
    return f"Gemini could not generate the brief: {text[:220]}"


def generate_morning_brief(summary: dict, risks: pd.DataFrame, equipment: pd.DataFrame) -> str:
    """Generate one brief or raise a clear, user-facing MorningBriefError."""
    status = get_ai_status()
    if not status["ready"]:
        raise MorningBriefError(status["message"])

    try:
        from google import genai

        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        response = client.models.generate_content(
            model=os.getenv("GEMINI_MODEL", DEFAULT_MODEL),
            contents=_build_prompt(summary, risks, equipment),
        )
        if not response.text:
            raise MorningBriefError("Gemini returned an empty brief. Please try again.")
        return response.text.strip()
    except MorningBriefError:
        raise
    except Exception as error:
        raise MorningBriefError(_friendly_error(error)) from error
