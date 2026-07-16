"""SwiftServe Operations Intelligence Dashboard.

Run from the project root:
    .\\.venv\\Scripts\\streamlit.exe run app.py
"""

from datetime import datetime
from html import escape
from io import BytesIO

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from services.ai_brief_service import generate_morning_brief, get_ai_status
from services.kpi_service import build_kpi_summary

try:
    from streamlit_autorefresh import st_autorefresh
except ImportError:
    st_autorefresh = None


st.set_page_config(
    page_title="SwiftServe | Operations Intelligence",
    page_icon="S",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_data(ttl=300, show_spinner=False)
def load_kpis() -> dict:
    """Read the current SwiftServe operational snapshot."""
    return build_kpi_summary()


def number(value, decimals: int = 0) -> str:
    if pd.isna(value):
        return "N/A"
    return f"{float(value):,.{decimals}f}"


def pill_class(value: str) -> str:
    return {
        "BREACHED": "danger",
        "AT_RISK": "warning",
        "ON_TRACK": "good",
        "NO_SLA_DATA": "muted",
        "OVERDUE": "danger",
        "DUE_SOON": "warning",
        "SCHEDULED": "good",
        "NO_SCHEDULE": "muted",
        "Active": "good",
        "Inactive": "muted",
        "Degraded": "warning",
    }.get(str(value), "muted")


def html_block(content: str) -> None:
    st.markdown(content, unsafe_allow_html=True)


def plot_style(figure, height: int = 305):
    """Use a consistent executive-chart treatment."""
    figure.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=height,
        margin={"l": 4, "r": 10, "t": 18, "b": 6},
        font={"family": "Inter, ui-sans-serif, Segoe UI, sans-serif", "color": "#c9d5e8"},
        hoverlabel={
            "bgcolor": "#121d31",
            "bordercolor": "#31415f",
            "font": {"color": "#f8fbff"},
        },
        showlegend=False,
    )
    figure.update_xaxes(gridcolor="rgba(148,163,184,.12)", zeroline=False, showline=False)
    figure.update_yaxes(gridcolor="rgba(148,163,184,.10)", zeroline=False, showline=False)
    return figure


def build_recommendations(
    risks: pd.DataFrame,
    equipment: pd.DataFrame,
    sla: dict,
) -> list[dict]:
    """Create deterministic operational recommendations from the live KPI data."""
    recommendations = []
    breached = risks.loc[risks["risk_flag"].eq("BREACHED")]
    if not breached.empty:
        ticket = breached.iloc[0]
        recommendations.append(
            {
                "type": "Escalate now",
                "tone": "danger",
                "title": f"Protect {ticket['work_order_id']} before further SLA impact",
                "detail": (
                    f"Contact {ticket['customer_name']} and confirm technician progress. "
                    f"The work order is beyond its resolution window."
                ),
            }
        )

    if not equipment.empty:
        asset = equipment.sort_values("critical_alerts", ascending=False).iloc[0]
        recommendations.append(
            {
                "type": "Asset risk",
                "tone": "warning",
                "title": f"Inspect {asset['equipment_name']}",
                "detail": (
                    f"{asset['critical_alerts']} unresolved critical alerts and "
                    f"a {asset['status']} status require preventive action."
                ),
            }
        )

    below_target = pd.DataFrame(sla["customers_below_threshold"])
    if not below_target.empty:
        customer = below_target.sort_values("sla_compliance_percent").iloc[0]
        recommendations.append(
            {
                "type": "Customer health",
                "tone": "violet",
                "title": f"Schedule an account review with {customer['customer_name']}",
                "detail": (
                    f"SLA compliance is {customer['sla_compliance_percent']}% with "
                    f"{customer['sla_breaches_this_month']} breach(es) this month."
                ),
            }
        )

    if not recommendations:
        recommendations.append(
            {
                "type": "Operationally healthy",
                "tone": "good",
                "title": "No high-priority intervention is needed",
                "detail": "Continue monitoring current workloads and customer commitments.",
            }
        )
    return recommendations


def build_pdf_report(summary: dict, risks: pd.DataFrame, recommendations: list[dict]) -> bytes:
    """Build a small executive PDF without sending data outside the computer."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph("SwiftServe Operations Intelligence", styles["Title"]),
        Paragraph(
            f"Executive snapshot · {datetime.now().strftime('%d %b %Y, %H:%M')}",
            styles["Normal"],
        ),
        Spacer(1, 12),
    ]
    data = [
        ["Open tickets", str(summary["open_tickets"]["count"])],
        ["SLA compliance", f"{summary['sla_compliance']['overall_avg_compliance_percent']}%"],
        ["SLA breaches", str(int(risks["risk_flag"].eq("BREACHED").sum()))],
        ["Equipment alerts", str(len(summary["critical_equipment"]))],
    ]
    table = Table(data, colWidths=[8 * cm, 7 * cm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f1f5f9")),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#0f172a")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("PADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.extend([table, Spacer(1, 16), Paragraph("Recommended actions", styles["Heading2"])])
    for item in recommendations:
        story.append(Paragraph(f"<b>{item['title']}</b><br/>{item['detail']}", styles["BodyText"]))
        story.append(Spacer(1, 7))

    story.append(Spacer(1, 8))
    story.append(Paragraph("Priority work queue", styles["Heading2"]))
    for _, ticket in risks.head(8).iterrows():
        story.append(
            Paragraph(
                f"<b>{ticket['work_order_id']}</b> · {ticket['customer_name']} · "
                f"{ticket['priority']} · {ticket['risk_flag']}",
                styles["BodyText"],
            )
        )
    document.build(story)
    return buffer.getvalue()


st.markdown(
    """
    <style>
      :root { --ink:#f7fbff; --muted:#91a1b9; --line:rgba(148,163,184,.15); --glass:rgba(16,27,47,.70); --cyan:#61dafb; --violet:#9b8afb; --rose:#fb7185; --amber:#f8bd5a; --green:#72e6b0; }
      .stApp { background:#07101f; }.stApp::before { content:"";position:fixed;inset:0;pointer-events:none;background:radial-gradient(600px 360px at 12% -4%,rgba(23,147,203,.18),transparent 65%),radial-gradient(600px 480px at 92% 2%,rgba(122,92,238,.15),transparent 67%),linear-gradient(180deg,#081222 0%,#070f1d 55%,#060c17 100%);z-index:0;}[data-testid="stAppViewContainer"]>.main{position:relative;z-index:1}[data-testid="stHeader"]{background:rgba(7,16,31,.65);backdrop-filter:blur(14px)}[data-testid="stSidebar"]{background:linear-gradient(180deg,rgba(11,21,40,.97),rgba(5,12,24,.98));border-right:1px solid var(--line)}[data-testid="stSidebar"]>div:first-child{padding-top:1.4rem}.block-container{max-width:1440px;padding:1.2rem 2.3rem 3rem}
      .side-brand{display:flex;align-items:center;gap:11px;margin:0 0 1.7rem}.side-mark{width:34px;height:34px;display:grid;place-items:center;border-radius:11px;color:#06111d;font-weight:800;background:linear-gradient(135deg,#83e8fb,#9185ff);box-shadow:0 8px 20px rgba(97,218,251,.18)}.side-title{color:#f8fbff;font-size:15px;font-weight:700}.side-caption{color:#7890ae;font-size:9px;letter-spacing:.13em;margin-top:1px}.side-label{color:#61738f;font-size:10px;letter-spacing:.12em;font-weight:700;margin:21px 0 7px}.side-status{display:flex;gap:8px;align-items:center;color:#b8c7d9;font-size:12px;padding:10px 0;border-bottom:1px solid var(--line)}.side-status b{margin-left:auto;color:#e5eefb;font-size:12px}.side-pulse{width:7px;height:7px;border-radius:99px;background:var(--green);box-shadow:0 0 12px var(--green);animation:pulse 2.2s ease-in-out infinite}
      div[data-testid="stSidebar"] button{border:1px solid rgba(97,218,251,.30)!important;color:#dff8ff!important;background:linear-gradient(100deg,rgba(29,121,163,.46),rgba(76,54,156,.50))!important;box-shadow:0 10px 24px rgba(1,10,25,.28);border-radius:10px!important;font-weight:650!important}.stTextInput input,.stMultiSelect [data-baseweb="select"]>div,.stSelectbox [data-baseweb="select"]>div{background:rgba(12,23,42,.82)!important;border-color:rgba(148,163,184,.22)!important;border-radius:9px!important;color:#eaf2fc!important}.stTextInput label,.stMultiSelect label,.stSelectbox label,.stToggle label{color:#a9b9cf!important;font-size:11px!important}.stDownloadButton button{border:1px solid rgba(148,163,184,.25)!important;border-radius:9px!important;background:rgba(17,31,54,.8)!important;color:#dcecff!important;font-weight:600!important}
      .topbar{display:flex;justify-content:space-between;align-items:center;padding:5px 0 18px}.crumb{color:#7789a6;font-size:12px}.crumb strong{color:#dbe9fb;font-weight:650}.live-state{display:flex;align-items:center;gap:8px;color:#a8dcbf;font-size:11px;padding:6px 10px;border:1px solid rgba(114,230,176,.18);border-radius:99px;background:rgba(23,99,70,.15)}.live-state i{width:6px;height:6px;display:block;border-radius:99px;background:var(--green);box-shadow:0 0 9px var(--green)}
      .hero{position:relative;overflow:hidden;min-height:236px;padding:34px 38px;border:1px solid rgba(136,176,221,.19);border-radius:20px;background:linear-gradient(112deg,rgba(13,39,69,.92),rgba(28,23,73,.88));box-shadow:0 28px 70px rgba(1,8,21,.32),inset 0 1px 0 rgba(255,255,255,.03);animation:rise .52s ease both}.hero::before{content:"";position:absolute;right:-110px;top:-210px;width:490px;height:490px;border-radius:50%;background:radial-gradient(circle,rgba(112,221,255,.19),rgba(112,221,255,0) 65%)}.hero::after{content:"";position:absolute;right:13%;bottom:-190px;width:330px;height:330px;border:1px solid rgba(161,144,255,.17);border-radius:50%;box-shadow:0 0 0 38px rgba(161,144,255,.035),0 0 0 76px rgba(161,144,255,.025)}.hero-grid{position:relative;z-index:1;display:flex;align-items:center;justify-content:space-between;gap:40px}.eyebrow{color:#92e6f7;font-size:10px;font-weight:700;letter-spacing:.16em}.hero h1{color:var(--ink);font-size:34px;line-height:1.12;letter-spacing:-.045em;margin:10px 0 11px;max-width:650px}.hero p{color:#b7c7dc;max-width:590px;line-height:1.6;font-size:14px;margin:0}.hero-meta{margin-top:20px;display:flex;align-items:center;gap:10px;color:#a6bbd3;font-size:11px}.hero-meta span{width:4px;height:4px;border-radius:50%;background:#7493b4}.health-orbit{flex:0 0 148px;width:148px;height:148px;border-radius:50%;background:conic-gradient(#71e7b0 calc(var(--health)*1%),rgba(255,255,255,.10) 0);display:grid;place-items:center;box-shadow:0 0 50px rgba(114,230,176,.14)}.health-inner{width:119px;height:119px;border-radius:50%;display:grid;place-items:center;text-align:center;background:rgba(8,19,36,.88);border:1px solid rgba(255,255,255,.09)}.health-number{color:#f7fbff;font-size:28px;font-weight:760;letter-spacing:-.05em}.health-caption{color:#95a9c1;font-size:10px;margin-top:-4px}
      .alert-banner{display:flex;align-items:center;gap:13px;margin:15px 0;border:1px solid rgba(251,113,133,.30);border-radius:12px;padding:12px 15px;background:linear-gradient(90deg,rgba(136,19,55,.28),rgba(51,25,45,.30));color:#ffe4e9;animation:rise .45s ease both}.alert-dot{width:8px;height:8px;border-radius:99px;background:#fb7185;box-shadow:0 0 12px #fb7185}.alert-copy{font-size:12px}.alert-copy b{font-weight:720}.alert-action{margin-left:auto;color:#fdb7c2;font-size:10px;letter-spacing:.05em}
      .metric-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px;margin:15px 0 34px}.metric-card{min-height:103px;padding:16px;border-radius:14px;border:1px solid var(--line);background:linear-gradient(145deg,rgba(18,31,53,.77),rgba(10,20,37,.68));box-shadow:0 12px 32px rgba(1,9,22,.17);animation:rise .54s ease both}.metric-card:nth-child(2){animation-delay:.04s}.metric-card:nth-child(3){animation-delay:.08s}.metric-card:nth-child(4){animation-delay:.12s}.metric-card:nth-child(5){animation-delay:.16s}.metric-label{color:#8da0bb;font-size:11px;font-weight:600}.metric-value{color:#f8fbff;font-size:29px;line-height:1;font-weight:760;letter-spacing:-.05em;margin:14px 0 8px}.metric-foot{color:#7386a3;font-size:10px}.metric-accent{width:28px;height:2px;border-radius:99px;margin-top:11px;background:var(--cyan)}.metric-accent.rose{background:var(--rose)}.metric-accent.amber{background:var(--amber)}.metric-accent.green{background:var(--green)}.metric-accent.violet{background:var(--violet)}
      .section-top{display:flex;align-items:end;justify-content:space-between;margin:0 0 13px}.section-kicker{color:#6fbad0;font-size:10px;letter-spacing:.15em;font-weight:700}.section-title{color:#edf4ff;font-size:19px;font-weight:720;letter-spacing:-.025em;margin-top:5px}.section-detail{color:#8497b2;font-size:11px;white-space:nowrap}.glass-panel{border:1px solid var(--line);border-radius:16px;background:linear-gradient(145deg,rgba(15,28,50,.70),rgba(10,19,35,.54));box-shadow:0 18px 38px rgba(1,9,23,.16);overflow:hidden}.queue-head,.queue-row{display:grid;grid-template-columns:84px minmax(130px,1.2fr) minmax(110px,1fr) 84px 92px;align-items:center;gap:10px}.queue-head{padding:12px 17px;color:#6f829f;font-size:9px;letter-spacing:.12em;font-weight:700;background:rgba(255,255,255,.018)}.queue-row{padding:14px 17px;border-top:1px solid rgba(148,163,184,.10);transition:background .18s ease}.queue-row:hover{background:rgba(97,218,251,.045)}.ticket-id{color:#dcecff;font-size:12px;font-weight:700}.customer-name{color:#e6effb;font-size:12px;font-weight:650}.ticket-site{color:#8295af;font-size:10px;margin-top:3px}.ticket-meta{color:#9fb2ca;font-size:11px}.status-pill{display:inline-flex;justify-content:center;padding:5px 7px;border-radius:99px;font-size:9px;font-weight:700;letter-spacing:.03em}.status-pill.danger{color:#fecdd3;background:rgba(190,24,93,.16);border:1px solid rgba(251,113,133,.23)}.status-pill.warning{color:#fde5a7;background:rgba(180,113,12,.17);border:1px solid rgba(248,189,90,.22)}.status-pill.good{color:#bdf5d6;background:rgba(17,123,81,.17);border:1px solid rgba(114,230,176,.20)}.status-pill.muted{color:#b5c2d5;background:rgba(100,116,139,.15);border:1px solid rgba(148,163,184,.16)}
      .brief,.recommendation-panel,.system-panel{padding:17px}.brief-item,.recommendation-item{padding:13px 0;border-top:1px solid rgba(148,163,184,.11)}.brief-item:first-of-type,.recommendation-item:first-of-type{border-top:0}.brief-top{display:flex;align-items:center;gap:8px;color:#f4f8ff;font-size:12px;font-weight:680}.brief-priority{margin-left:auto;color:#fdcbd2;background:rgba(190,24,93,.16);padding:3px 6px;border-radius:99px;font-size:9px}.brief-copy,.rec-detail{color:#8fa2bc;font-size:11px;line-height:1.45;margin:6px 0 0 15px}.brief-dot{width:7px;height:7px;border-radius:50%;background:var(--rose);box-shadow:0 0 10px rgba(251,113,133,.8)}.rec-top{display:flex;align-items:center;gap:8px;color:#f1f6ff;font-size:12px;font-weight:680}.rec-type{font-size:9px;letter-spacing:.04em;border-radius:99px;padding:3px 7px}.rec-type.danger{color:#fecdd3;background:rgba(190,24,93,.16)}.rec-type.warning{color:#fde5a7;background:rgba(180,113,12,.17)}.rec-type.violet{color:#dcd6ff;background:rgba(109,92,204,.18)}.rec-type.good{color:#bdf5d6;background:rgba(17,123,81,.17)}.empty-state{padding:30px 0;color:#9fb4ca;font-size:12px}[data-testid="stVerticalBlockBorderWrapper"]{border:1px solid var(--line)!important;border-radius:16px!important;background:linear-gradient(145deg,rgba(15,28,50,.70),rgba(10,19,35,.54))!important;box-shadow:0 18px 38px rgba(1,9,23,.16)!important}
      .chart-shell{border:1px solid var(--line);border-radius:16px;background:linear-gradient(145deg,rgba(15,28,50,.66),rgba(9,18,33,.48));padding:15px 14px 5px;box-shadow:0 18px 38px rgba(1,9,23,.14)}.chart-label{color:#edf4ff;font-size:13px;font-weight:680}.chart-note{color:#8195b2;font-size:10px;margin-top:4px}.watch-list{padding:0 17px}.watch-row{display:grid;grid-template-columns:1fr auto;gap:14px;padding:14px 0;border-top:1px solid rgba(148,163,184,.11)}.watch-row:first-child{border-top:0}.watch-name{color:#e9f1fc;font-size:12px;font-weight:650}.watch-meta{color:#8296b1;font-size:10px;margin-top:4px}.watch-number{color:#f7cad1;font-size:15px;font-weight:760;text-align:right}.watch-caption{color:#7f92ac;font-size:9px;margin-top:3px;text-align:right}.team-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.team-card{padding:13px;border:1px solid var(--line);border-radius:13px;background:rgba(15,27,48,.56);transition:transform .18s ease,border-color .18s ease}.team-card:hover{transform:translateY(-2px);border-color:rgba(97,218,251,.31)}.team-name{color:#ecf4ff;font-size:12px;font-weight:680}.team-meta{color:#8094af;font-size:10px;margin-top:4px}.team-rate{color:#79e8ba;font-size:18px;font-weight:760;letter-spacing:-.04em;margin-top:13px}.team-rate span{color:#7f91ab;font-size:9px;font-weight:500;letter-spacing:0}.health-list{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.health-item{padding:13px;border:1px solid var(--line);border-radius:12px;background:rgba(10,21,39,.48)}.health-label{color:#8295af;font-size:10px}.health-value{color:#ecf5ff;font-size:13px;font-weight:680;margin-top:7px}.health-value.good{color:#9df0c8}.health-value.warning{color:#fde5a7}.ai-copy{color:#bcd0e6;font-size:13px;line-height:1.7}.ai-copy h1,.ai-copy h2,.ai-copy h3{color:#eff6ff;font-size:15px;margin:15px 0 5px}.footer-note{color:#6f829e;font-size:10px;padding:22px 0 4px;border-top:1px solid var(--line);margin-top:28px}
      .glass-panel.system-panel:empty,.chart-shell:empty{display:none}.ai-state-card{padding:18px;border:1px solid var(--line);border-radius:16px;background:linear-gradient(145deg,rgba(15,28,50,.70),rgba(10,19,35,.54));box-shadow:0 18px 38px rgba(1,9,23,.16)}.ai-state-title{color:#edf4ff;font-size:13px;font-weight:680;margin-bottom:6px}.ai-state-copy{color:#91a4bd;font-size:11px;line-height:1.55}
      .mode-note{color:#8195b2;font-size:11px;margin:2px 0 16px}
      @keyframes rise{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}@keyframes pulse{0%,100%{opacity:.7}50%{opacity:1}}@media(max-width:900px){.metric-grid{grid-template-columns:repeat(2,1fr)}.hero-grid{align-items:flex-start}.health-orbit{flex-basis:118px;width:118px;height:118px}.health-inner{width:93px;height:93px}.hero h1{font-size:27px}.queue-head,.queue-row{grid-template-columns:70px 1fr 80px}.queue-row .ticket-meta,.queue-head .hide-small{display:none}.team-grid{grid-template-columns:repeat(2,1fr)}}@media(max-width:560px){.block-container{padding:1rem}.metric-grid{grid-template-columns:1fr 1fr;gap:8px}.metric-card{padding:12px;min-height:90px}.hero{padding:24px 22px}.hero-grid{display:block}.health-orbit{margin-top:22px}.queue-head,.queue-row{grid-template-columns:66px 1fr 75px;padding-left:12px;padding-right:12px}.queue-row .customer-name{font-size:11px}.section-detail{display:none}.health-list{grid-template-columns:1fr}}
    </style>
    """,
    unsafe_allow_html=True,
)


with st.sidebar:
    html_block(
        """
        <div class="side-brand"><div class="side-mark">S</div><div><div class="side-title">SwiftServe</div><div class="side-caption">OPERATIONS INTELLIGENCE</div></div></div>
        <div class="side-label">WORKSPACE FILTERS</div>
        """
    )
    search_term = st.text_input("Search customer, ticket, or location", placeholder="Search operations")
    selected_risk = st.multiselect("SLA status", ["BREACHED", "AT_RISK", "ON_TRACK", "NO_SLA_DATA"])
    auto_refresh = st.toggle("Auto refresh every 5 minutes", value=True)


try:
    with st.spinner("Loading live operational signals..."):
        summary = load_kpis()
except Exception as error:
    st.error("SwiftServeDB could not be reached.")
    st.exception(error)
    st.stop()


open_tickets = summary["open_tickets"]
all_risk_df = summary["tickets_at_risk"].copy()
sla = summary["sla_compliance"]
equipment_df = summary["critical_equipment"].copy()
technicians_df = summary["technician_performance"].copy()
dispatch = summary["dispatch_performance"]
zones_df = summary["zone_summary"].copy()
maintenance_df = summary["maintenance_due"].copy()
skill_df = summary["skill_match"].copy()
cycle_df = summary["cycle_time_trends"].copy()
bottleneck_df = summary["bottleneck_analysis"].copy()

locations = sorted(all_risk_df["location"].dropna().unique().tolist())
priorities = sorted(all_risk_df["priority"].dropna().unique().tolist())

with st.sidebar:
    selected_location = st.multiselect("Location", locations, key="location_filter")
    selected_priority = st.multiselect("Priority", priorities, key="priority_filter")

if auto_refresh and st_autorefresh is not None:
    st_autorefresh(interval=300_000, key="swiftserve_auto_refresh")

risk_rank = {"BREACHED": 0, "AT_RISK": 1, "ON_TRACK": 2, "NO_SLA_DATA": 3}
risk_df = all_risk_df.copy()
if selected_risk:
    risk_df = risk_df.loc[risk_df["risk_flag"].isin(selected_risk)]
if selected_location:
    risk_df = risk_df.loc[risk_df["location"].isin(selected_location)]
if selected_priority:
    risk_df = risk_df.loc[risk_df["priority"].isin(selected_priority)]
if search_term.strip():
    searchable = risk_df[["work_order_id", "customer_name", "location"]].astype(str).agg(" ".join, axis=1)
    risk_df = risk_df.loc[searchable.str.contains(search_term.strip(), case=False, na=False, regex=False)]
risk_df["_rank"] = risk_df["risk_flag"].map(risk_rank).fillna(4)
risk_df = risk_df.sort_values(["_rank", "elapsed_hours"])

global_breaches = all_risk_df.loc[all_risk_df["risk_flag"].eq("BREACHED")]
overdue_by_due_date = all_risk_df.loc[all_risk_df["is_overdue"]]
at_risk_count = int(all_risk_df["risk_flag"].eq("AT_RISK").sum())
compliance = float(sla["overall_avg_compliance_percent"])
ai_status = get_ai_status()
gemini_ready = ai_status["ready"]
recommendations = build_recommendations(all_risk_df, equipment_df, sla)

with st.sidebar:
    html_block(
        f"""
        <div class="side-label">SYSTEM HEALTH</div>
        <div class="side-status"><span class="side-pulse"></span>SQL data feed <b>Healthy</b></div>
        <div class="side-status">Gemini briefing <b>{ai_status['label']}</b></div>
        <div class="side-status">Auto refresh <b>{'On' if auto_refresh else 'Off'}</b></div>
        <div class="side-label">EXPORTS</div>
        """
    )
    st.button("Refresh live signals", use_container_width=True, type="primary", on_click=st.cache_data.clear)

    csv_bytes = risk_df.drop(columns=["_rank"], errors="ignore").to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download filtered CSV",
        csv_bytes,
        file_name="swiftserve_priority_queue.csv",
        mime="text/csv",
        use_container_width=True,
    )
    try:
        pdf_bytes = build_pdf_report(summary, all_risk_df, recommendations)
    except ImportError:
        pdf_bytes = None
    if pdf_bytes is not None:
        st.download_button(
            "Download executive PDF",
            pdf_bytes,
            file_name="swiftserve_executive_brief.pdf",
            mime="application/pdf",
            use_container_width=True,
        )
    else:
        st.caption("Install requirements to enable PDF export.")


html_block(
    f"""
    <div class="topbar"><div class="crumb"><strong>Operations</strong> / Command center</div><div class="live-state"><i></i>Live snapshot · refreshed {datetime.now().strftime('%d %b %Y, %H:%M')}</div></div>
    <section class="hero"><div class="hero-grid"><div><div class="eyebrow">FIELD SERVICE INTELLIGENCE</div><h1>Operational clarity,<br>at the speed of the field.</h1><p>One command surface for SLA exposure, technician execution, equipment risk, and customer health.</p><div class="hero-meta">SwiftServeDB <span></span> Enterprise operations view <span></span> Five-minute refresh cadence</div></div><div class="health-orbit" style="--health:{min(max(compliance, 0), 100):.1f}"><div class="health-inner"><div><div class="health-number">{number(compliance)}%</div><div class="health-caption">SLA health</div></div></div></div></div></section>
    """
)

if not global_breaches.empty:
    html_block(
        f'<div class="alert-banner"><span class="alert-dot"></span><div class="alert-copy"><b>{len(global_breaches)} SLA breach(es) need action.</b> Prioritise the command brief before assigning new routine work.</div><div class="alert-action">HIGH PRIORITY</div></div>'
    )
elif at_risk_count:
    html_block(
        f'<div class="alert-banner" style="border-color:rgba(248,189,90,.28);background:linear-gradient(90deg,rgba(112,70,14,.23),rgba(51,40,23,.24));"><span class="alert-dot" style="background:#f8bd5a;box-shadow:0 0 12px #f8bd5a"></span><div class="alert-copy"><b>{at_risk_count} ticket(s) are approaching the SLA window.</b> Confirm technician progress now.</div><div class="alert-action" style="color:#fde5a7">WATCH</div></div>'
    )

metric_cards = [
    ("Open work orders", number(open_tickets["count"]), "Across active field operations", "cyan"),
    ("SLA breaches", number(len(global_breaches)), "Requires immediate escalation", "rose"),
    ("Approaching SLA", number(at_risk_count), "Within the intervention window", "amber"),
    ("Customer health", f"{number(compliance)}%", "Average compliance across accounts", "green"),
    ("Equipment watchlist", number(len(equipment_df)), "Degraded or high-alert assets", "violet"),
]
html_block(
    '<div class="metric-grid">'
    + "".join(
        f'<div class="metric-card"><div class="metric-label">{escape(label)}</div><div class="metric-value">{escape(value)}</div><div class="metric-foot">{escape(foot)}</div><div class="metric-accent {accent}"></div></div>'
        for label, value, foot, accent in metric_cards
    )
    + "</div>"
)

act_tab, observe_tab, explore_tab = st.tabs(
    ["🔧  ACT · Immediate Action", "📊  OBSERVE · Historical Analysis", "🧭  EXPLORE · Strategic Intelligence"]
)

# =====================================================================
# ACT MODE — reactive: what needs a decision right now?
# =====================================================================
with act_tab:
    html_block('<div class="mode-note">Overdue work, SLA breaches, critical equipment, and the recommended next move — everything a dispatcher needs before assigning new work.</div>')

    left, right = st.columns([1.75, 1], gap="large")
    with left:
        html_block('<div class="section-top"><div><div class="section-kicker">PRIORITY QUEUE</div><div class="section-title">Work requiring a decision</div></div><div class="section-detail">Filtered by your workspace controls</div></div>')
        queue_rows = []
        for _, ticket in risk_df.head(8).iterrows():
            target = ticket["resolution_time_target_hours"]
            elapsed = ticket["elapsed_hours"]
            sla_text = "No target" if pd.isna(target) else f"{number(elapsed, 1)}h elapsed"
            overdue_tag = ' <span class="status-pill danger" style="margin-left:6px">PAST DUE_DATE</span>' if ticket["is_overdue"] else ""
            queue_rows.append(
                f"""<div class="queue-row"><div class="ticket-id">{escape(str(ticket['work_order_id']))}</div><div><div class="customer-name">{escape(str(ticket['customer_name']))}</div><div class="ticket-site">{escape(str(ticket['location']))}</div></div><div class="ticket-meta">{escape(sla_text)}</div><div class="ticket-meta">{escape(str(ticket['priority']))}</div><div><span class="status-pill {pill_class(ticket['risk_flag'])}">{escape(str(ticket['risk_flag']).replace('_', ' '))}</span>{overdue_tag}</div></div>"""
            )
        if queue_rows:
            html_block('<div class="glass-panel"><div class="queue-head"><div>CASE</div><div>CUSTOMER / SITE</div><div class="hide-small">ELAPSED</div><div class="hide-small">PRIORITY</div><div>STATUS</div></div>' + "".join(queue_rows) + "</div>")
        else:
            html_block('<div class="glass-panel"><div class="empty-state">No work orders match the selected filters.</div></div>')
        st.caption(f"{len(overdue_by_due_date)} open work order(s) are past their contractual due_date (independent of SLA-window risk above).")

    with right:
        html_block('<div class="section-top"><div><div class="section-kicker">RECOMMENDATION ENGINE</div><div class="section-title">What to do next</div></div></div>')
        recommendation_html = []
        for item in recommendations:
            recommendation_html.append(
                f'<div class="recommendation-item"><div class="rec-top"><span class="rec-type {item["tone"]}">{escape(item["type"].upper())}</span>{escape(item["title"])}</div><div class="rec-detail">{escape(item["detail"])}</div></div>'
            )
        html_block('<div class="glass-panel recommendation-panel">' + "".join(recommendation_html) + "</div>")

    st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
    ai_left, ai_right = st.columns([1.35, 1], gap="large")
    with ai_left:
        html_block('<div class="section-top"><div><div class="section-kicker">AI MORNING BRIEF</div><div class="section-title">Executive narrative, on demand</div></div><div class="section-detail">Gemini · aggregate KPI context</div></div><div class="glass-panel system-panel">')
        if not gemini_ready:
            html_block(f'<div class="ai-state-card"><div class="ai-state-title">Connect Gemini to generate the morning brief</div><div class="ai-state-copy">{escape(ai_status["message"])}</div></div>')
        else:
            if st.button("Generate AI morning brief", type="primary", key="generate_brief"):
                try:
                    with st.spinner("Gemini is preparing the morning brief..."):
                            st.session_state["morning_brief"] = generate_morning_brief(summary, all_risk_df, equipment_df)
                except Exception as error:
                    st.session_state["morning_brief_error"] = str(error)
                if st.session_state.get("morning_brief_error"):
                    st.error(st.session_state["morning_brief_error"])
                elif st.session_state.get("morning_brief"):
                    st.markdown(st.session_state["morning_brief"])
            else:
                html_block('<div class="empty-state">Generate a concise leadership briefing from the current operational snapshot.</div>')
        html_block("</div>")

    with ai_right:
        html_block('<div class="section-top"><div><div class="section-kicker">SYSTEM HEALTH</div><div class="section-title">Platform readiness</div></div></div><div class="glass-panel system-panel"><div class="health-list">')
        health_items = [
            ("Data source", "SQL connected", "good"),
            ("AI briefing", "Gemini ready" if gemini_ready else "API key needed", "good" if gemini_ready else "warning"),
            ("Refresh cadence", "5 minutes" if auto_refresh else "Manual", "good" if auto_refresh else "warning"),
        ]
        health_html = "".join(
            f'<div class="health-item"><div class="health-label">{label}</div><div class="health-value {tone}">{value}</div></div>'
            for label, value, tone in health_items
        )
        html_block(f'<div class="glass-panel system-panel"><div class="health-list">{health_html}</div></div>')
        html_block("</div></div>")

    st.markdown("<div style='height:26px'></div>", unsafe_allow_html=True)
    bottom_left, bottom_right = st.columns([1.1, 1], gap="large")
    with bottom_left:
        html_block('<div class="section-top"><div><div class="section-kicker">ASSET HEALTH</div><div class="section-title">Equipment watchlist</div></div><div class="section-detail">Critical alerts and status</div></div><div class="glass-panel"><div class="watch-list">')
        if equipment_df.empty:
            html_block('<div class="empty-state">No assets are in a critical state.</div>')
        else:
            rows = []
            for _, asset in equipment_df.sort_values("critical_alerts", ascending=False).iterrows():
                rows.append(f'<div class="watch-row"><div><div class="watch-name">{escape(str(asset["equipment_name"]))}</div><div class="watch-meta">{escape(str(asset["equipment_id"]))} · {escape(str(asset["status"]))}</div></div><div><div class="watch-number">{number(asset["critical_alerts"])}</div><div class="watch-caption">critical alerts</div></div></div>')
            html_block("".join(rows))
        html_block("</div></div>")

    with bottom_right:
        html_block('<div class="section-top"><div><div class="section-kicker">DRILL DOWN</div><div class="section-title">Inspect a work order</div></div><div class="section-detail">Filtered priority queue</div></div><div class="glass-panel system-panel">')
        if risk_df.empty:
            html_block('<div class="empty-state">Change the filters to select a work order.</div>')
        else:
            selected_id = st.selectbox("Choose a work order", risk_df["work_order_id"].tolist(), label_visibility="collapsed")
            selected_ticket = risk_df.loc[risk_df["work_order_id"].eq(selected_id)].iloc[0]
            target = selected_ticket["resolution_time_target_hours"]
            target_text = "No SLA target available" if pd.isna(target) else f"{number(target, 1)} hour resolution target"
            due_text = "past due_date" if selected_ticket["is_overdue"] else "within due_date"
            html_block(
                f"""
                <div class="brief-item"><div class="brief-top"><span class="brief-dot"></span>{escape(str(selected_ticket['work_order_id']))} · {escape(str(selected_ticket['customer_name']))}<span class="brief-priority">{escape(str(selected_ticket['priority']))}</span></div>
                <div class="brief-copy">{escape(str(selected_ticket['location']))} · {number(selected_ticket['elapsed_hours'], 1)} hours elapsed · {escape(target_text)} · {escape(due_text)} · <span class="status-pill {pill_class(selected_ticket['risk_flag'])}">{escape(str(selected_ticket['risk_flag']).replace('_', ' '))}</span></div></div>
                """
            )
        html_block("</div>")

# =====================================================================
# OBSERVE MODE — historical: how has the team and the book of business performed?
# =====================================================================
with observe_tab:
    html_block('<div class="mode-note">Technician performance, dispatch execution, customer trends, and cycle-time history — what happened, and how it compares over time.</div>')

    chart_left, chart_right = st.columns(2, gap="large")
    with chart_left:
        html_block('<div class="chart-shell"><div class="chart-label">Operational load by location</div><div class="chart-note">Open cases compared with overdue work orders</div>')
        zone_chart_data = zones_df.sort_values(["overdue_tickets", "open_tickets"], ascending=False)
        workload = go.Figure()
        workload.add_bar(
            name="Open",
            x=zone_chart_data["location"],
            y=zone_chart_data["open_tickets"],
            marker_color="#61dafb",
            marker_line_width=0,
            hovertemplate="%{x}<br>Open work orders: %{y}<extra></extra>",
        )
        workload.add_bar(
            name="Overdue",
            x=zone_chart_data["location"],
            y=zone_chart_data["overdue_tickets"],
            marker_color="#fb7185",
            marker_line_width=0,
            hovertemplate="%{x}<br>Overdue work orders: %{y}<extra></extra>",
        )
        workload.update_layout(barmode="group", yaxis_title="Work orders", legend={"orientation": "h", "y": 1.12})
        workload.update_layout(showlegend=True)
        st.plotly_chart(plot_style(workload), use_container_width=True, config={"displayModeBar": False})
        html_block("</div>")

    with chart_right:
        html_block('<div class="chart-shell"><div class="chart-label">Customer confidence</div><div class="chart-note">SLA compliance, uptime, and breach history by account</div>')
        customers = sla["all_customers"].sort_values("sla_compliance_percent")
        health_chart = px.bar(
            customers,
            x="sla_compliance_percent",
            y="customer_name",
            orientation="h",
            text="sla_compliance_percent",
            color="sla_compliance_percent",
            color_continuous_scale=["#fb7185", "#f8bd5a", "#72e6b0"],
            range_color=[70, 100],
            labels={"sla_compliance_percent": "Compliance (%)", "customer_name": ""},
            custom_data=["actual_uptime_percent", "sla_breaches_this_month"],
        )
        health_chart.update_traces(
            texttemplate="%{text:.0f}%",
            textposition="outside",
            hovertemplate="%{y}<br>SLA compliance: %{x:.1f}%<br>Uptime: %{customdata[0]:.1f}%<br>Breaches this month: %{customdata[1]}<extra></extra>",
        )
        health_chart.update_layout(coloraxis_showscale=False, xaxis={"range": [65, 108]}, yaxis_title=None)
        st.plotly_chart(plot_style(health_chart), use_container_width=True, config={"displayModeBar": False})
        html_block("</div>")

    st.markdown("<div style='height:26px'></div>", unsafe_allow_html=True)
    obs_left, obs_right = st.columns([1.3, 1], gap="large")
    with obs_left:
        html_block('<div class="section-top"><div><div class="section-kicker">FIELD TEAM</div><div class="section-title">Technician performance rankings</div></div><div class="section-detail">Completion rate · avg response time</div></div>')
        tech_display = technicians_df.rename(columns={
            "name": "Technician",
            "location": "Location",
            "status": "Status",
            "skills": "Skills",
            "total_assignments": "Assignments",
            "completion_rate_percent": "Completion %",
            "avg_response_time_hours": "Avg Response (h)",
        })[["Technician", "Location", "Status", "Skills", "Assignments", "Completion %", "Avg Response (h)"]]
        st.dataframe(tech_display, use_container_width=True, hide_index=True)

    with obs_right:
        html_block('<div class="section-top"><div><div class="section-kicker">FIELD EXECUTION</div><div class="section-title">Dispatch performance</div></div></div><div class="glass-panel system-panel"><div class="health-list" style="grid-template-columns:1fr">')
        dispatch_items = [
            ("Avg dispatch-to-arrival", f"{number(dispatch['average_response_time_hours'], 2)} hours", "good"),
            ("Avg customer feedback", f"{number(dispatch['average_customer_feedback'], 2)} / 5", "good"),
        ]
        dispatch_html = "".join(
            f'<div class="health-item"><div class="health-label">{label}</div><div class="health-value {tone}">{value}</div></div>'
            for label, value, tone in dispatch_items
        )
        breakdown = ", ".join(f"{k}: {v}" for k, v in dispatch["dispatch_status_breakdown"].items())
        html_block(f'<div class="glass-panel system-panel"><div class="health-list" style="grid-template-columns:1fr">{dispatch_html}<div class="health-item"><div class="health-label">Dispatch status mix</div><div class="health-value">{escape(breakdown)}</div></div></div></div>')
        html_block("</div></div>")

    st.markdown("<div style='height:26px'></div>", unsafe_allow_html=True)
    html_block('<div class="chart-shell"><div class="chart-label">Work order cycle-time trend</div><div class="chart-note">Average resolution time for completed work, by creation date</div>')
    if cycle_df.empty:
        html_block('<div class="empty-state">Not enough completed work orders yet to plot a trend.</div>')
    else:
        trend_chart = go.Figure()
        trend_chart.add_scatter(
            x=cycle_df["date"].astype(str),
            y=cycle_df["avg_resolution_time_hours"],
            mode="lines+markers",
            line={"color": "#61dafb", "width": 2.5},
            marker={"size": 7, "color": "#9b8afb"},
            hovertemplate="%{x}<br>Avg resolution time: %{y:.1f}h<extra></extra>",
        )
        trend_chart.update_layout(yaxis_title="Avg resolution time (hours)", xaxis_title=None)
        st.plotly_chart(plot_style(trend_chart, height=260), use_container_width=True, config={"displayModeBar": False})
    html_block("</div>")

# =====================================================================
# EXPLORE MODE — strategic: what should we plan for next?
# =====================================================================
with explore_tab:
    html_block('<div class="mode-note">Preventive maintenance, skill-based resourcing, customer risk scoring, and bottleneck analysis — forward-looking signals for planning.</div>')

    exp_left, exp_right = st.columns([1.2, 1], gap="large")
    with exp_left:
        html_block('<div class="section-top"><div><div class="section-kicker">PREVENTIVE MAINTENANCE</div><div class="section-title">Equipment nearing its service window</div></div><div class="section-detail">Overdue or due within 30 days</div></div><div class="glass-panel"><div class="watch-list">')
        if maintenance_df.empty:
            html_block('<div class="empty-state">No equipment is overdue or due soon for maintenance.</div>')
        else:
            rows = []
            for _, asset in maintenance_df.iterrows():
                days = asset["days_until_due"]
                day_text = f"{abs(int(days))} days overdue" if days < 0 else f"due in {int(days)} days"
                rows.append(
                    f'<div class="watch-row"><div><div class="watch-name">{escape(str(asset["equipment_name"]))}</div><div class="watch-meta">{escape(str(asset["equipment_id"]))} · {escape(str(asset["location"]))}</div></div><div><span class="status-pill {pill_class(asset["maintenance_status"])}">{escape(str(asset["maintenance_status"]).replace("_", " "))}</span><div class="watch-caption">{escape(day_text)}</div></div></div>'
                )
            html_block("".join(rows))
        html_block("</div></div>")

    with exp_right:
        html_block('<div class="section-top"><div><div class="section-kicker">CUSTOMER RISK</div><div class="section-title">Accounts at risk of churn</div></div><div class="section-detail">Ranked by compliance, breaches, uptime</div></div>')
        risk_score_df = sla["all_customers"].copy()
        risk_score_df["risk_score"] = (
            (100 - risk_score_df["sla_compliance_percent"]) * 0.5
            + risk_score_df["sla_breaches_this_month"] * 8
            + (100 - risk_score_df["actual_uptime_percent"]) * 0.5
        ).round(1)
        risk_score_df = risk_score_df.sort_values("risk_score", ascending=False)
        risk_display = risk_score_df.rename(columns={
            "customer_name": "Customer",
            "sla_tier": "Tier",
            "sla_compliance_percent": "Compliance %",
            "sla_breaches_this_month": "Breaches (mo.)",
            "actual_uptime_percent": "Uptime %",
            "risk_score": "Risk Score",
        })[["Customer", "Tier", "Compliance %", "Breaches (mo.)", "Uptime %", "Risk Score"]]
        st.dataframe(risk_display, use_container_width=True, hide_index=True)
        st.caption("Risk score is a simple weighted blend of compliance shortfall, monthly breaches, and uptime shortfall — higher means more attention needed, not a contractual metric.")

    st.markdown("<div style='height:26px'></div>", unsafe_allow_html=True)
    exp2_left, exp2_right = st.columns([1.2, 1], gap="large")
    with exp2_left:
        html_block('<div class="section-top"><div><div class="section-kicker">RESOURCE ALLOCATION</div><div class="section-title">Best technician for open work</div></div><div class="section-detail">Skill-matched, ranked by completion rate</div></div>')
        if skill_df.empty:
            html_block('<div class="glass-panel"><div class="empty-state">No open work orders need reassignment right now.</div></div>')
        else:
            skill_display = skill_df.rename(columns={
                "work_order_id": "Work Order",
                "issue_type": "Issue Type",
                "location": "Location",
                "current_technician": "Currently Assigned",
                "recommended_technician": "Recommended",
                "match_basis": "Match Basis",
                "recommended_completion_rate": "Completion %",
            })
            st.dataframe(skill_display, use_container_width=True, hide_index=True)

    with exp2_right:
        html_block('<div class="section-top"><div><div class="section-kicker">BOTTLENECK ANALYSIS</div><div class="section-title">Slowest issue types</div></div><div class="section-detail">Avg resolution time, by category</div></div>')
        bottleneck_chart_df = bottleneck_df.dropna(subset=["avg_resolution_time_hours"])
        if bottleneck_chart_df.empty:
            html_block('<div class="glass-panel"><div class="empty-state">Not enough completed data yet to rank bottlenecks.</div></div>')
        else:
            bottleneck_chart = px.bar(
                bottleneck_chart_df.sort_values("avg_resolution_time_hours"),
                x="avg_resolution_time_hours",
                y="issue_type",
                orientation="h",
                text="avg_resolution_time_hours",
                labels={"avg_resolution_time_hours": "Avg resolution time (h)", "issue_type": ""},
            )
            bottleneck_chart.update_traces(
                marker_color="#f8bd5a",
                texttemplate="%{text:.1f}h",
                textposition="outside",
                hovertemplate="%{y}<br>Avg resolution time: %{x:.1f}h<extra></extra>",
            )
            st.plotly_chart(plot_style(bottleneck_chart, height=280), use_container_width=True, config={"displayModeBar": False})

html_block('<div class="footer-note">SwiftServe Operations Intelligence · Live SQL Server data · AI briefings are generated only when requested</div>')
