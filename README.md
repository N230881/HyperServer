# HyperServe — Multithreaded HTTP Server

A production-inspired HTTP server built **from raw TCP sockets** (no Flask/FastAPI/Django) in
pure Python, with a thread pool, routing + middleware, an LRU cache, structured JSON logging,
a benchmarking tool, unit tests, and a live **Streamlit** monitoring dashboard.

Everything runs **100% locally** — no paid APIs, no external services, no signup required.

---

## 1. Folder Structure

```
hyperserve/
├── server/                    # Core engine (the "framework" layer)
│   ├── __init__.py
│   ├── socket_server.py       # Raw TCP listener + connection lifecycle
│   ├── thread_pool.py         # Hand-rolled thread pool (Queue + workers)
│   ├── http_parser.py         # Parses raw bytes -> HTTPRequest
│   ├── router.py              # HashMap routing + dynamic params + middleware chain
│   ├── middleware.py          # timing, security headers, rate limiter
│   ├── response.py            # Builds raw HTTP/1.1 responses
│   └── logger.py              # Structured JSON access logging
│
├── app/                       # Your application (the "app" layer)
│   ├── __init__.py
│   ├── routes.py              # All routes: /, /api/health, /api/items, /static/<file>, /metrics
│   └── static/
│       └── index.html         # Sample static file (served + LRU cached)
│
├── dashboard/
│   └── streamlit_app.py       # Live monitoring dashboard (traffic, latency, cache, logs)
│
├── tests/
│   └── test_server.py         # Unit tests for parser, cache, router
│
├── logs/
│   └── access_log.jsonl       # Auto-generated structured logs (one JSON object per line)
│
├── main.py                    # Entry point — starts the server
├── benchmark.py                # Load-testing / throughput & latency benchmarking tool
├── requirements.txt            # Only needed for the dashboard (server has zero deps)
└── README.md
```

---

## 2. How it maps to the handbook

| Handbook feature        | Where it lives |
|---|---|
| Thread Pool              | `server/thread_pool.py` |
| HTTP request parsing     | `server/http_parser.py` |
| Routing + Middleware      | `server/router.py`, `server/middleware.py` |
| LRU Cache                 | `server/lru_cache.py`, used in `app/routes.py` for static files |
| Structured Logging        | `server/logger.py` (JSON Lines format) |
| Metrics Dashboard          | `dashboard/streamlit_app.py` + `GET /metrics` |
| Queues (request scheduling) | `queue.Queue` inside `ThreadPool` |
| HashMap (routing)          | `Router.static_routes` dict |
| Concurrency & Synchronization | `threading.Lock` in `ThreadPool`, `LRUCache`, `RateLimiter` |
| Security headers            | `response.py` (`DEFAULT_SECURITY_HEADERS`), `middleware.py` |
| Unit tests                  | `tests/test_server.py` |
| Benchmarking                 | `benchmark.py` |

---

## 3. Step-by-Step Setup (on your laptop)

### Step 1 — Install Python
You need **Python 3.9+**. Check with:
```bash
python3 --version
```
If you don't have it, download from https://www.python.org/downloads/ (free, official source).

### Step 2 — Get the project onto your laptop
Unzip the `hyperserve` folder you downloaded (or `git clone` if you push it to your own repo),
then open a terminal inside it:
```bash
cd hyperserve
```

### Step 3 — (Recommended) Create a virtual environment
This keeps HyperServe's dependencies isolated from the rest of your system.
```bash
python3 -m venv venv

# Activate it:
source venv/bin/activate        # macOS/Linux
venv\Scripts\activate           # Windows (PowerShell: venv\Scripts\Activate.ps1)
```

### Step 4 — Install dependencies
The **server itself needs zero third-party packages** (pure standard library — `socket`,
`threading`, `queue`, etc.). You only need to install anything if you want the dashboard:
```bash
pip install -r requirements.txt
```

### Step 5 — Run the server
```bash
python main.py --host 127.0.0.1 --port 8080 --threads 8
```
You should see:
```
HyperServe listening on http://127.0.0.1:8080
Thread pool size: 8
```
Leave this terminal running.

### Step 6 — Try it in a browser or with curl
Open a **second terminal** (keep the server running in the first):
```bash
curl http://127.0.0.1:8080/api/health
curl http://127.0.0.1:8080/api/echo?name=you
curl -X POST http://127.0.0.1:8080/api/items -d '{"name":"widget"}'
curl http://127.0.0.1:8080/api/items/1
curl http://127.0.0.1:8080/metrics
```
Or just open `http://127.0.0.1:8080/` in your browser — it serves the static HTML page
(cached by the LRU cache after the first hit).

### Step 7 — Run the Streamlit dashboard
In a **third terminal** (server still running in terminal 1):
```bash
source venv/bin/activate     # if you used a venv
streamlit run dashboard/streamlit_app.py
```
This opens a browser tab (usually `http://localhost:8501`) showing:
- Live uptime, requests/sec, active worker threads, queue size
- Cache hit rate
- Traffic-over-time chart, top requested paths
- Status code distribution, HTTP method breakdown
- Latency histogram + scatter plot
- Raw request log table (searchable/sortable)
- A sidebar to **fire test requests** straight from the dashboard

Make sure the "Server base URL" field in the sidebar matches the host/port you started the
server with (default `http://127.0.0.1:8080`).

### Step 8 — Run the unit tests
```bash
python -m unittest tests/test_server.py -v
```

### Step 9 — Run the benchmark
With the server running in terminal 1:
```bash
python benchmark.py --url http://127.0.0.1:8080/api/health --requests 500 --concurrency 20
```
This prints requests/sec, average/median/P95 latency — paste these numbers into your resume
or report as your "performance results" (per the handbook's Originality Checklist).

---

## 4. How to use / extend it

### Add a new route
Edit `app/routes.py`:
```python
@router.get("/api/hello/<name>")
def say_hello(request, name):
    return json_response({"message": f"Hello, {name}!"})
```
Restart the server — no other file needs to change.

### Add a new middleware
Edit `server/middleware.py` (or write your own function with signature
`def my_mw(request, next_fn): ...`), then register it in `main.py`:
```python
router.use(my_mw)
```

### Change thread pool size / port
```bash
python main.py --host 0.0.0.0 --port 9000 --threads 16 --rate-limit 200
```
`--rate-limit N` caps each client to N requests/minute (0 disables it).

### Serve more static files
Drop files into `app/static/` and access them at `/static/<filename>` — the first request
reads from disk, subsequent requests are served from the in-memory LRU cache.

---

## 5. How this differs from a real production server (be transparent about this)

This is an **educational implementation**, not a replacement for NGINX/Apache. It doesn't do:
- Real TLS/HTTPS termination (would need `ssl.wrap_socket` + a cert — a good next step)
- HTTP/2 or keep-alive connection reuse (currently `Connection: close` per request)
- Chunked transfer encoding
- Full RFC-compliant HTTP parsing edge cases

These are good "future work" talking points for interviews (see the handbook's Interview
Questions section) — e.g. "How would you support HTTPS?" → wrap the raw socket in
`ssl.SSLContext.wrap_socket()` before the accept loop.

---

## 6. Resume bullets (from the handbook, ready to use)

- Built a multithreaded HTTP server from raw TCP sockets supporting concurrent client connections via a custom thread pool.
- Implemented routing with dynamic path parameters, a composable middleware chain, an LRU cache, and structured JSON logging.
- Built a Streamlit dashboard for real-time observability (throughput, latency percentiles, cache hit rate).
- Benchmarked the server under concurrent load, achieving measurable requests/sec and P95 latency figures with a custom load-testing script.
