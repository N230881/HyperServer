"""
dashboard/streamlit_app.py
---------------------------
Streamlit monitoring dashboard for HyperServe. Reads:
  1. logs/access_log.jsonl (via server.logger.read_recent_logs) for
     request-level history, charts, and tables.
  2. GET /metrics on the live server for real-time thread pool /
     cache stats.

Run with (from the project root, server already running separately):
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
from server.logger import read_recent_logs, clear_logs, ACCESS_LOG_PATH

st.set_page_config(page_title="HyperServe Dashboard", page_icon="⚡", layout="wide")


# ----------------------------------------------------------------------
# Sidebar: connection settings + live actions
# ----------------------------------------------------------------------

st.sidebar.title("⚡ HyperServe")
st.sidebar.caption("Multithreaded HTTP Server — Live Dashboard")

server_url = st.sidebar.text_input("Server base URL", value="http://127.0.0.1:8080")
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
        url = server_url.rstrip("/") + test_path
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
# Fetch live /metrics from the server (thread pool + cache state)
# ----------------------------------------------------------------------

def fetch_metrics(base_url):
    try:
        with urllib.request.urlopen(base_url.rstrip("/") + "/metrics", timeout=2) as resp:
            return json.loads(resp.read().decode("utf-8")), None
    except Exception as e:
        return None, str(e)


metrics, metrics_err = fetch_metrics(server_url)

st.title("HyperServe Monitoring Dashboard")

if metrics_err:
    st.warning(
        f"Could not reach {server_url}/metrics ({metrics_err}). "
        f"Start the server with `python main.py` and confirm the URL/port match."
    )
else:
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
# Load request logs into a DataFrame
# ----------------------------------------------------------------------

logs = read_recent_logs(limit=log_limit)

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
        st.caption(f"Log file: `{ACCESS_LOG_PATH}`")

if auto_refresh:
    time.sleep(3)
    st.rerun()
