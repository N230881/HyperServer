"""
app/routes.py
--------------
All user-facing routes live here, separate from the core server engine.
This is the "app" layer on top of HyperServe's "framework" layer -
mirroring how you'd structure a real backend service.
"""

import os
import mimetypes
import time

from server.router import Router
from server.response import (
    text_response, html_response, json_response, file_response, error_response,
)
from server.lru_cache import LRUCache

router = Router()

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
static_cache = LRUCache(capacity=64)

# in-memory demo "database" for a small CRUD API
_items_db = {}
_next_id = [1]


# ---------------------------------------------------------------------
# Basic routes
# ---------------------------------------------------------------------

@router.get("/")
def home(request):
    return html_response(_render_static("index.html"))


@router.get("/api/health")
def health(request):
    return json_response({"status": "ok", "server": "HyperServe", "time": time.time()})


@router.get("/api/echo")
def echo(request):
    return json_response({
        "method": request.method,
        "path": request.path,
        "query": request.query,
        "headers": request.headers,
    })


@router.post("/api/echo")
def echo_post(request):
    try:
        payload = request.json()
    except Exception:
        payload = request.body.decode("utf-8", errors="replace")
    return json_response({"you_sent": payload})


# ---------------------------------------------------------------------
# Small CRUD API (demonstrates dynamic route params: /api/items/<id>)
# ---------------------------------------------------------------------

@router.get("/api/items")
def list_items(request):
    return json_response({"items": list(_items_db.values())})


@router.post("/api/items")
def create_item(request):
    body = request.json() or {}
    item_id = _next_id[0]
    _next_id[0] += 1
    item = {"id": item_id, "name": body.get("name", "unnamed")}
    _items_db[item_id] = item
    return json_response(item, status_code=201)


@router.get("/api/items/<item_id>")
def get_item(request, item_id):
    item = _items_db.get(int(item_id))
    if not item:
        return error_response(404, f"Item {item_id} not found")
    return json_response(item)


@router.delete("/api/items/<item_id>")
def delete_item(request, item_id):
    item = _items_db.pop(int(item_id), None)
    if not item:
        return error_response(404, f"Item {item_id} not found")
    return json_response({"deleted": item_id})


# ---------------------------------------------------------------------
# Metrics endpoint (used by the Streamlit dashboard, and useful on its own)
# ---------------------------------------------------------------------

def build_metrics_route(server_ref):
    @router.get("/metrics")
    def metrics(request):
        data = server_ref.stats()
        data["cache"] = static_cache.stats()
        return json_response(data)
    return metrics


@router.post("/debug/clear-cache")
def clear_cache(request):
    """Dev-only endpoint used by benchmark.py to force a cold-cache
    measurement. Not something you'd ship to production as-is."""
    static_cache.clear()
    return json_response({"cleared": True})


# ---------------------------------------------------------------------
# Static file serving, with LRU cache
# ---------------------------------------------------------------------

@router.get("/static/<filename>")
def serve_static(request, filename):
    return _serve_static_file(request, filename)


def _serve_static_file(request, filename):
    safe_name = os.path.basename(filename)  # prevent path traversal
    cached = static_cache.get(safe_name)
    if cached is not None:
        request._cache_hit = True
        content, content_type = cached
        return file_response(content, content_type)

    full_path = os.path.join(STATIC_DIR, safe_name)
    if not os.path.isfile(full_path):
        return error_response(404, f"Static file not found: {safe_name}")

    with open(full_path, "rb") as f:
        content = f.read()
    content_type = mimetypes.guess_type(full_path)[0] or "application/octet-stream"
    static_cache.put(safe_name, (content, content_type))
    return file_response(content, content_type)


def _render_static(filename):
    cached = static_cache.get(filename)
    if cached is not None:
        return cached[0].decode("utf-8")
    full_path = os.path.join(STATIC_DIR, filename)
    with open(full_path, "rb") as f:
        content = f.read()
    static_cache.put(filename, (content, "text/html"))
    return content.decode("utf-8")