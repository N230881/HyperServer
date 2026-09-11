"""
logger.py
---------
Structured logging: every request is written as one JSON line to
logs/access_log.jsonl. This is what the Streamlit dashboard tails to
render live metrics (requests/sec, status code distribution, latency).
"""

import json
import os
import threading
import time
from datetime import datetime

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
ACCESS_LOG_PATH = os.path.join(LOG_DIR, "access_log.jsonl")

_write_lock = threading.Lock()


def _ensure_log_dir():
    os.makedirs(LOG_DIR, exist_ok=True)


def log_request(method, path, status_code, duration_ms, client_addr, cache_hit=False, thread_name=""):
    _ensure_log_dir()
    entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "epoch": time.time(),
        "method": method,
        "path": path,
        "status_code": status_code,
        "duration_ms": round(duration_ms, 3),
        "client": f"{client_addr[0]}:{client_addr[1]}" if client_addr else "unknown",
        "cache_hit": cache_hit,
        "thread": thread_name,
    }
    line = json.dumps(entry)
    with _write_lock:
        with open(ACCESS_LOG_PATH, "a") as f:
            f.write(line + "\n")
    # also echo to console for live terminal feedback
    print(f"[{entry['timestamp']}] {method} {path} -> {status_code} "
          f"({entry['duration_ms']}ms) {'[CACHE HIT]' if cache_hit else ''}")
    return entry


def read_recent_logs(limit=500):
    _ensure_log_dir()
    if not os.path.exists(ACCESS_LOG_PATH):
        return []
    with open(ACCESS_LOG_PATH, "r") as f:
        lines = f.readlines()[-limit:]
    out = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def clear_logs():
    _ensure_log_dir()
    with _write_lock:
        open(ACCESS_LOG_PATH, "w").close()
