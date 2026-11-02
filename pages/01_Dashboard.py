"""Executive dashboard for the Healthcare AI Data Platform (Snowflake Streamlit)."""
import html
import pandas as pd
import streamlit as st
from snowflake.snowpark.context import get_active_session
from utils.config_loader import load_config
from services.dashboard_service import (
    get_all_source_metrics, get_registry_metrics, get_error_metrics,
    get_recent_errors, get_recent_registry_entries, get_mapping_metrics,
)
from style_utils import render_header

render_header()

st.set_page_config(page_title="Healthcare Data Platform | Overview", page_icon="🏥", layout="wide")

st.markdown("""
<style>
.block-container {max-width: 1500px; padding-top: 1.5rem; padding-bottom: 3rem;}
h1,h2,h3 {letter-spacing: -.025em;}
.hero {background: linear-gradient(115deg,#102b46,#13556a); border-radius:18px; padding:26px 32px; color:white; margin-bottom:24px;}
.hero .eyebrow {font-size:12px; letter-spacing:2px; color:#a6e3df; font-weight:700;}
.hero h1 {font-size:32px; color:white; margin:8px 0 6px;}
.hero p {color:#d7e8ee; margin:0; font-size:14px;}
.kpi {background: #fff; border:1px solid #e4eaf0; border-radius:14px; padding:20px; min-height:128px; box-shadow:0 3px 14px rgba(16,43,70,.04);}
.kpi .label {color:#62748a; font-size:13px; font-weight:600;}
.kpi .value {color:#102b46; font-size:30px; font-weight:750; margin:8px 0 4px;}
.kpi .note {color:#738396; font-size:12px;}
.section-label {font-size:19px; font-weight:750; color:#102b46; margin:24px 0 12px;}
.source {border:1px solid #e4eaf0; border-radius:14px; padding:18px 20px; background:white; margin-bottom:8px;}
.source-head {display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;}
.source-title {font-weight:750; font-size:18px; color:#102b46;}
.source-rate {font-weight:700; color:#0c827b;}
.bar-track {height:9px; border-radius:9px; background:#eaf1f4; overflow:hidden; margin:10px 0 14px;}
.bar-fill {height:100%; border-radius:9px; background:linear-gradient(90deg,#15a89b,#50c9bb);}
.source-meta {display:flex; justify-content:space-between; font-size:12px; color:#617389; flex-wrap:wrap; gap:6px;}
.note-box {background:#f0f7f9; border-left:3px solid #169a98; padding:12px 16px; border-radius:6px; color:#33536a; font-size:13px;}
@media (prefers-color-scheme: dark) {.kpi,.source {background:#152536; border-color:#34465b;} .kpi .value,.source-title,.section-label {color:#f2f7fa;} .kpi .label,.source-meta {color:#a7b9ca;}}
</style>
""", unsafe_allow_html=True)


def num(value):
    try:
        return int(value) if value is not None else 0
    except (ValueError, TypeError):
        return 0


def metric(data, key):
    return num((data or {}).get(key))


def kpi(label, value, note=""):
    st.markdown(
        f'<div class="kpi"><div class="label">{html.escape(str(label))}</div>'
        f'<div class="value">{html.escape(str(value))}</div>'
        f'<div class="note">{html.escape(str(note))}</div></div>',
        unsafe_allow_html=True,
    )


def section(label):
    st.markdown(f'<div class="section-label">{html.escape(label)}</div>', unsafe_allow_html=True)


config = load_config()
session = get_active_session()

st.markdown('''<div class="hero"><div class="eyebrow">HEALTHCARE DATA PLATFORM / OPERATIONS</div>
<h1>Data Pipeline Overview</h1><p>FHIR · JSON · XML &nbsp; | &nbsp; Snowflake ingestion, AI flattening and pipeline monitoring</p></div>''', unsafe_allow_html=True)

left, right = st.columns([5, 1])
with left:
    st.caption("Operational snapshot · Metrics reflect the current Snowflake table contents")
with right:
    if st.button("↻ Refresh data", use_container_width=True):
        st.rerun()

try:
    with st.spinner("Loading pipeline metrics…"):
        sources = get_all_source_metrics(session, config) or {}
        registry = get_registry_metrics(session, config) or {}
        errors = get_error_metrics(session, config) or {}
        mappings = get_mapping_metrics(session, config) or {}
except Exception as exc:
    st.error(f"Unable to load dashboard metrics: {exc}")
    st.stop()

source_names = ["FHIR", "JSON", "XML"]
total = sum(metric(sources.get(s), "total") for s in source_names)
processed = sum(metric(sources.get(s), "processed") for s in source_names)
pending = sum(metric(sources.get(s), "pending") for s in source_names)
unmapped = sum(metric(sources.get(s), "unmapped") for s in source_names)
rate = 100 * processed / total if total else 0

section("Executive summary")
cols = st.columns(5, gap="medium")
for col, args in zip(cols, [
    ("Raw records", f"{total:,}", "Across all sources"),
    ("Processed", f"{processed:,}", "Marked as processed"),
    ("Pending", f"{pending:,}", "Awaiting processing"),
    ("Processing rate", f"{rate:.1f}%", "Processed / total records"),
    ("Unmapped", f"{unmapped:,}", "No target table assigned"),
]):
    with col:
        kpi(*args)

section("Ingestion & source performance")
source_cols = st.columns(3, gap="medium")
for col, name in zip(source_cols, source_names):
    data = sources.get(name) or {}
    n = metric(data, "total")
    done = metric(data, "processed")
    waiting = metric(data, "pending")
    missing = metric(data, "unmapped")
    unhashed = metric(data, "unhashed")
    pct = 100 * done / n if n else 0
    with col:
        st.markdown(
            f'<div class="source"><div class="source-head"><span class="source-title">{name}</span>'
            f'<span class="source-rate">{pct:.1f}% processed</span></div>'
            f'<div class="source-meta"><span><b>{n:,}</b> total records</span><span><b>{done:,}</b> processed</span></div>'
            f'<div class="bar-track"><div class="bar-fill" style="width:{min(100, max(0, pct)):.2f}%"></div></div>'
            f'<div class="source-meta"><span>Pending: <b>{waiting:,}</b></span>'
            f'<span>Unmapped: <b>{missing:,}</b></span><span>Unhashed: <b>{unhashed:,}</b></span></div></div>',
            unsafe_allow_html=True,
        )

chart_col, error_col = st.columns([1.35, 1], gap="large")
with chart_col:
    section("Processing by source")
    source_chart = pd.DataFrame([
        {"Source": s, "Processed": metric(sources.get(s), "processed"),
         "Pending": metric(sources.get(s), "pending")}
        for s in source_names
    ]).set_index("Source")
    st.bar_chart(source_chart, color=["#149b92", "#f2b36b"], height=280)
    st.caption("Counts are based on PROCESSED_FLAG; unmapped is a separate overlapping category.")
with error_col:
    section("Pipeline error breakdown")
    error_labels = {
        "fingerprint": "Fingerprint", "cortex": "Cortex generation",
        "validation": "Validation", "repair": "Cortex repair", "execution": "Flatten execution",
    }
    error_chart = pd.DataFrame([
        {"Stage": label, "Errors": metric(errors, key)} for key, label in error_labels.items()
    ]).set_index("Stage")
    st.bar_chart(error_chart, color="#dc776d", height=280)
    st.caption(f"{metric(errors, 'total'):,} logged error events (historical total, not active failures).")

section("AI flattening & metadata")
cols = st.columns(4, gap="medium")
for col, args in zip(cols, [
    ("Cached flatten queries", f"{metric(registry, 'total_queries'):,}", "Query registry entries"),
    ("Unique structures", f"{metric(registry, 'structures'):,}", "Distinct structure hashes"),
    ("Target tables", f"{metric(registry, 'target_tables'):,}", "Registry target tables"),
    ("Source types", f"{metric(registry, 'source_types'):,}", "Represented in registry"),
]):
    with col:
        kpi(*args)

st.markdown('<div class="note-box">Cache-hit rate and Cortex-call savings are not shown because the current control tables do not record those execution events.</div>', unsafe_allow_html=True)

section("Source-to-target mapping coverage")
cols = st.columns(4, gap="medium")
for col, args in zip(cols, [
    ("Total mappings", f"{metric(mappings, 'total'):,}", "Configured mapping rows"),
    ("FHIR mappings", f"{metric(mappings, 'fhir'):,}", "FHIR source rows"),
    ("JSON mappings", f"{metric(mappings, 'json'):,}", "JSON source rows"),
    ("XML mappings", f"{metric(mappings, 'xml'):,}", "XML source rows"),
]):
    with col:
        kpi(*args)

section("Recent operational activity")
registry_tab, errors_tab = st.tabs(["Recent cached queries", "Recent errors"])
with registry_tab:
    try:
        df = get_recent_registry_entries(session, config)
        if df is None or df.empty:
            st.info("No registry entries available.")
        else:
            st.dataframe(df, use_container_width=True, hide_index=True)
    except Exception as exc:
        st.error(f"Unable to load registry activity: {exc}")
with errors_tab:
    try:
        df = get_recent_errors(session, config)
        if df is None or df.empty:
            st.info("No error log entries available.")
        else:
            st.dataframe(df, use_container_width=True, hide_index=True)
    except Exception as exc:
        st.error(f"Unable to load recent errors: {exc}")

st.divider()
st.caption("Healthcare AI Data Platform · Snowflake operational dashboard")
