"""
Gemini-powered morning brief service for the SwiftServe dashboard.
Works on:
1. Local PC using .env
2. Streamlit Cloud using Secrets
"""

import os
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"
DEFAULT_MODEL = "gemini-3.5-flash"


class MorningBriefError(RuntimeError):
    pass


def _load_environment():
    """Load .env only if it exists."""
    if ENV_FILE.exists():
        load_dotenv(ENV_FILE, override=False)


def get_ai_status():

    _load_environment()

    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        try:
            api_key = st.secrets["GEMINI_API_KEY"]
        except Exception:
            api_key = ""

    model = os.getenv("GEMINI_MODEL")

    if not model:
        try:
            model = st.secrets["GEMINI_MODEL"]
        except Exception:
            model = DEFAULT_MODEL

    if not api_key:
        return {
            "ready": False,
            "label": "API Key Missing",
            "message": "Configure GEMINI_API_KEY in .env or Streamlit Secrets.",
        }

    try:
        from google import genai
    except ImportError:
        return {
            "ready": False,
            "label": "Gemini SDK Missing",
            "message": "Run: pip install google-genai",
        }

    return {
        "ready": True,
        "label": "Gemini Ready",
        "message": f"Model: {model}",
    }


def _build_prompt(summary, risks, equipment):

    risk_rows = risks.head(5)[
        [
            "work_order_id",
            "customer_name",
            "location",
            "priority",
            "risk_flag",
            "elapsed_hours",
        ]
    ].to_dict(orient="records")

    equipment_rows = equipment.head(5).to_dict(orient="records")

    sla = summary["sla_compliance"]

    return f"""
You are the Operations Head of SwiftServe.

Write a professional executive morning briefing.

Use exactly these headings:

1. Situation Now
2. Immediate Actions
3. Watch Items

Maximum 220 words.

Open Tickets:
{summary['open_tickets']['count']}

Average SLA Compliance:
{sla['overall_avg_compliance_percent']}%

Average Dispatch Response:
{summary['dispatch_performance']['average_response_time_hours']} hours

Average Customer Rating:
{summary['dispatch_performance']['average_customer_feedback']}

Tickets at Risk:
{risk_rows}

Equipment Watchlist:
{equipment_rows}

Customers below SLA:
{sla['customers_below_threshold']}
"""


def _friendly_error(error):

    text = str(error)

    if "API_KEY" in text.upper():
        return "Invalid Gemini API Key."

    if "MODEL" in text.upper():
        return "Gemini model not found."

    if "429" in text:
        return "Gemini rate limit exceeded."

    return text


def generate_morning_brief(summary, risks, equipment):

    status = get_ai_status()

    if not status["ready"]:
        raise MorningBriefError(status["message"])

    try:

        from google import genai

        api_key = os.getenv("GEMINI_API_KEY")

        if not api_key:
            api_key = st.secrets["GEMINI_API_KEY"]

        model = os.getenv("GEMINI_MODEL")

        if not model:
            model = st.secrets.get("GEMINI_MODEL", DEFAULT_MODEL)

        client = genai.Client(api_key=api_key)

        response = client.models.generate_content(
            model=model,
            contents=_build_prompt(summary, risks, equipment),
        )

        if not response.text:
            raise MorningBriefError("Gemini returned an empty response.")

        return response.text.strip()

    except MorningBriefError:
        raise

    except Exception as e:
        raise MorningBriefError(_friendly_error(e))
