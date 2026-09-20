"""
dashboard/streamlit_app.py
---------------------------
Streamlit monitoring dashboard for HyperServe.

TWO MODES:
  1. LIVE mode - if a HyperServe server is reachable at the "Server
     base URL" you provide (e.g. running locally on your own machine,
     or exposed via a tunnel like ngrok), the dashboard shows real,
     current data from GET /metrics and logs/access_log.jsonl.
  2. DEMO mode - if no live server is reachable (which is ALWAYS the
     case when this dashboard is deployed on Streamlit Community Cloud
     and HyperServe is only running on your own laptop - 127.0.0.1
     means "this machine", and Streamlit's cloud machine is not your
     laptop), it automatically falls back to sample data captured from
     a real local benchmark run. That sample data is embedded directly
     in dashboard/_demo_data.py (not a separate .jsonl file), so there
     is no risk of it going missing or being at the wrong path after
     uploading to GitHub / deploying on Streamlit Cloud.

Run locally with (from the project root, server running separately):
    streamlit run dashboard/streamlit_app.py

No paid APIs are used anywhere in this dashboard.
"""

import os
import sys
import time
import json
import urllib.request
import urllib.error

import streamlit as st
import pandas as pd
import plotly.express as px

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from server.logger import read_recent_logs, clear_logs, ACCESS_LOG_PATH
from _demo_data import get_demo_logs

st.set_page_config(page_title="HyperServe Dashboard", page_icon="⚡", layout="wide")


def _clean_base_url(raw: str) -> str:
    """Users sometimes paste the full /metrics URL instead of just the
    base URL, or leave stray whitespace. Normalize it so a request is
    never built with a duplicated path or control characters."""
    url = raw.strip()
    for suffix in ("/metrics", "/"):
        while url.endswith(suffix):
            url = url[: -len(suffix)]
    return url


def fetch_metrics(base_url):
    try:
        with urllib.request.urlopen(base_url + "/metrics", timeout=2) as resp:
            return json.loads(resp.read().decode("utf-8")), None
    except Exception as e:
        return None, str(e)


def load_demo_logs(limit):
    logs = get_demo_logs()
    return logs[-limit:]


def demo_metrics_from_logs(logs):
    """Builds a /metrics-shaped summary out of the bundled demo log,
    so the top metric cards can render in demo mode too."""
    if not logs:
        return None
    df = pd.DataFrame(logs)
    total = len(df)
    cache_hits = int(df["cache_hit"].sum()) if "cache_hit" in df else 0
    hit_rate = round(100 * cache_hits / total, 1) if total else 0.0
    span_s = max(1.0, (df["epoch"].max() - df["epoch"].min())) if "epoch" in df else 1.0
    return {
        "uptime_seconds": round(span_s, 1),
        "total_requests": total,
        "requests_per_sec": round(total / span_s, 2),
        "thread_pool": {"active_workers": 0, "num_threads": 8, "queue_size": 0,
                         "avg_wait_time_ms": 0.0},
        "cache": {"hit_rate_pct": hit_rate, "size": min(total, 32), "capacity": 64},
    }


# ----------------------------------------------------------------------
# Sidebar: connection settings + live actions
# ----------------------------------------------------------------------

st.sidebar.title("⚡ HyperServe")
st.sidebar.caption("Multithreaded HTTP Server — Live Dashboard")

server_url_raw = st.sidebar.text_input(
    "Server base URL",
    value="http://127.0.0.1:8080",
    help="Just the base, e.g. http://127.0.0.1:8080 — do NOT include /metrics. "
         "Only reachable if HyperServe is running on THIS same machine as this "
         "dashboard, or exposed via a public tunnel.",
)
server_url = _clean_base_url(server_url_raw)

auto_refresh = st.sidebar.checkbox("Auto-refresh every 3s", value=True)
log_limit = st.sidebar.slider("Log rows to load", 50, 5000, 1000, step=50)

st.sidebar.divider()
st.sidebar.subheader("Send a test request")
test_method = st.sidebar.selectbox("Method", ["GET", "POST"])
test_path = st.sidebar.text_input("Path", value="/api/health")
test_body = ""
if test_method == "POST":
    test_body = st.sidebar.text_area("JSON body", value='{"name": "widget"}')

if st.sidebar.button("Send request"):
    try:
        url = server_url + test_path
        if test_method == "GET":
            req = urllib.request.Request(url, method="GET")
        else:
            req = urllib.request.Request(
                url, data=test_body.encode("utf-8"), method="POST",
                headers={"Content-Type": "application/json"},
            )
        with urllib.request.urlopen(req, timeout=5) as resp:
            st.sidebar.success(f"Status {resp.status}")
            st.sidebar.code(resp.read().decode("utf-8"), language="json")
    except urllib.error.HTTPError as e:
        st.sidebar.error(f"HTTP {e.code}")
        st.sidebar.code(e.read().decode("utf-8"), language="json")
    except Exception as e:
        st.sidebar.error(f"Request failed: {e}")

st.sidebar.divider()
if st.sidebar.button("🗑️ Clear access log"):
    clear_logs()
    st.sidebar.success("Log cleared.")


# ----------------------------------------------------------------------
# Try LIVE data first; fall back to bundled DEMO data if unreachable
# ----------------------------------------------------------------------

metrics, metrics_err = fetch_metrics(server_url)
demo_mode = metrics_err is not None

st.title("HyperServe Monitoring Dashboard")

if demo_mode:
    st.info(
        f"⚠️ No live server reachable at **{server_url}** ({metrics_err}). "
        f"Showing **demo data** from a real local benchmark run instead. "
        f"To see live data: run `python main.py` on the **same machine** as "
        f"this dashboard (this only works when run locally — a deployed "
        f"cloud link can never reach `127.0.0.1` on your own laptop)."
    )
    logs = load_demo_logs(log_limit)
    metrics = demo_metrics_from_logs(logs)
else:
    st.success(f"✅ Connected to live server at {server_url}")
    logs = read_recent_logs(limit=log_limit)

if metrics:
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Uptime (s)", metrics["uptime_seconds"])
    col2.metric("Total Requests", metrics["total_requests"])
    col3.metric("Requests / sec", metrics["requests_per_sec"])
    col4.metric("Active Workers", f"{metrics['thread_pool']['active_workers']}/{metrics['thread_pool']['num_threads']}")
    col5.metric("Queue Size", metrics["thread_pool"]["queue_size"])

    col6, col7, col8 = st.columns(3)
    col6.metric("Cache Hit Rate", f"{metrics['cache']['hit_rate_pct']}%")
    col7.metric("Cache Size", f"{metrics['cache']['size']}/{metrics['cache']['capacity']}")
    col8.metric("Avg Queue Wait (ms)", metrics["thread_pool"]["avg_wait_time_ms"])

st.divider()

# ----------------------------------------------------------------------
# Request log table + charts (live or demo, same rendering either way)
# ----------------------------------------------------------------------

if not logs:
    st.info(
        "No requests logged yet. Hit some endpoints on the server "
        "(or use 'Send a test request' in the sidebar) and they'll appear here."
    )
else:
    df = pd.DataFrame(logs)
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    tab1, tab2, tab3, tab4 = st.tabs(
        ["📈 Traffic Over Time", "📊 Status Codes", "⚡ Latency", "📋 Raw Log"]
    )

    with tab1:
        df_time = df.set_index("timestamp").resample("1s").size().reset_index(name="requests")
        fig = px.line(df_time, x="timestamp", y="requests", title="Requests per second")
        st.plotly_chart(fig, use_container_width=True)

        path_counts = df["path"].value_counts().reset_index()
        path_counts.columns = ["path", "count"]
        fig2 = px.bar(path_counts.head(15), x="path", y="count", title="Top Requested Paths")
        st.plotly_chart(fig2, use_container_width=True)

    with tab2:
        status_counts = df["status_code"].value_counts().reset_index()
        status_counts.columns = ["status_code", "count"]
        status_counts["status_code"] = status_counts["status_code"].astype(str)
        fig3 = px.pie(status_counts, names="status_code", values="count",
                       title="Status Code Distribution", hole=0.4)
        st.plotly_chart(fig3, use_container_width=True)

        method_counts = df["method"].value_counts().reset_index()
        method_counts.columns = ["method", "count"]
        fig4 = px.bar(method_counts, x="method", y="count", title="Requests by HTTP Method")
        st.plotly_chart(fig4, use_container_width=True)

    with tab3:
        fig5 = px.histogram(df, x="duration_ms", nbins=40, title="Response Time Distribution (ms)")
        st.plotly_chart(fig5, use_container_width=True)

        fig6 = px.scatter(df, x="timestamp", y="duration_ms", color="status_code",
                           title="Latency Over Time", hover_data=["path", "method"])
        st.plotly_chart(fig6, use_container_width=True)

        cache_hits = df["cache_hit"].sum()
        st.metric("Cache Hits (this log window)", f"{cache_hits} / {len(df)}")

    with tab4:
        st.dataframe(
            df.sort_values("timestamp", ascending=False)[
                ["timestamp", "method", "path", "status_code", "duration_ms", "cache_hit", "client", "thread"]
            ],
            use_container_width=True,
            height=500,
        )
        st.caption(
            f"Log source: {'embedded demo data (sample run)' if demo_mode else ACCESS_LOG_PATH}"
        )

if auto_refresh and not demo_mode:
    # Don't auto-rerun in demo mode - it's static sample data, so
    # re-running every 3s would just burn Streamlit Cloud resources
    # for no visual change.
    time.sleep(3)
    st.rerun()