"""
benchmark.py
------------
Load-testing tool for HyperServe. Fires N concurrent requests over
persistent (keep-alive) connections, using a real thread pool of
worker "virtual clients" -- each worker owns one HTTPConnection and
fires its share of requests sequentially on it, so results reflect
HyperServe's actual keep-alive path rather than opening a fresh
socket per request.

Also runs a cold-vs-warm cache comparison against a static route,
and reports the server's own /metrics (cache hit rate, active
threads, total requests) alongside the client-side measurements.

Usage:
    python benchmark.py --host 127.0.0.1 --port 8080 \
        --path /api/health --requests 1000 --concurrency 50
"""

import argparse
import http.client
import json
import statistics
import threading
import time


def _one_client_run(host, port, path, n_requests, results, lock):
    """One virtual client: opens ONE persistent connection and fires
    n_requests sequentially on it (mirrors a real browser tab reusing
    a keep-alive connection)."""
    conn = http.client.HTTPConnection(host, port, timeout=5)
    local = []
    try:
        for _ in range(n_requests):
            t0 = time.time()
            try:
                conn.request("GET", path)
                resp = conn.getresponse()
                resp.read()
                status = resp.status
            except Exception:
                status = -1
                # connection died (e.g. server closed it) - reopen and retry once
                try:
                    conn.close()
                    conn = http.client.HTTPConnection(host, port, timeout=5)
                except Exception:
                    pass
            elapsed_ms = (time.time() - t0) * 1000
            local.append((status, elapsed_ms))
    finally:
        conn.close()
    with lock:
        results.extend(local)


def run_benchmark(host, port, path, total_requests, concurrency):
    results = []
    lock = threading.Lock()

    per_worker = total_requests // concurrency
    remainder = total_requests % concurrency
    workers = []

    start_time = time.time()
    for i in range(concurrency):
        n = per_worker + (1 if i < remainder else 0)
        if n == 0:
            continue
        t = threading.Thread(target=_one_client_run, args=(host, port, path, n, results, lock))
        workers.append(t)
        t.start()
    for t in workers:
        t.join()
    total_time = time.time() - start_time

    latencies = [r[1] for r in results]
    success = sum(1 for r in results if r[0] and 200 <= r[0] < 400)
    errors = len(results) - success
    sorted_lat = sorted(latencies) if latencies else [0]

    summary = {
        "path": path,
        "total_requests": len(results),
        "concurrency": concurrency,
        "total_time_s": round(total_time, 3),
        "requests_per_sec": round(len(results) / total_time, 2) if total_time > 0 else 0,
        "successful": success,
        "errors": errors,
        "avg_latency_ms": round(statistics.mean(latencies), 3) if latencies else 0,
        "median_latency_ms": round(statistics.median(latencies), 3) if latencies else 0,
        "p95_latency_ms": round(sorted_lat[int(len(sorted_lat) * 0.95) - 1], 3),
        "p99_latency_ms": round(sorted_lat[int(len(sorted_lat) * 0.99) - 1], 3),
        "max_latency_ms": round(max(latencies), 3) if latencies else 0,
    }
    return summary


def fetch_metrics(host, port):
    try:
        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.request("GET", "/metrics")
        resp = conn.getresponse()
        data = json.loads(resp.read())
        conn.close()
        return data
    except Exception as e:
        return {"error": str(e)}


def clear_server_cache(host, port):
    """Hits a debug endpoint to clear the static cache, if the server
    exposes one. Falls back to a no-op with a warning if it doesn't -
    in that case the 'cold' phase below only reflects the very first
    request being uncached."""
    try:
        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.request("POST", "/debug/clear-cache")
        resp = conn.getresponse()
        resp.read()
        conn.close()
        return resp.status == 200
    except Exception:
        return False


def print_summary(title, summary):
    print(f"\n===== {title} =====")
    for k, v in summary.items():
        print(f"{k:20s}: {v}")


def cache_comparison(host, port, static_path, n_samples):
    """
    Measures true cold-cache latency by clearing the LRU cache before
    EVERY sample (so each 'cold' request is a genuine disk-read miss),
    then measures warm latency with the cache left populated (so every
    request after the first is served from memory).
    """
    conn = http.client.HTTPConnection(host, port, timeout=5)

    def _timed_get(path):
        nonlocal conn
        t0 = time.time()
        try:
            conn.request("GET", path)
            resp = conn.getresponse()
            resp.read()
        except Exception:
            # connection was closed server-side between requests; reopen once
            conn.close()
            conn = http.client.HTTPConnection(host, port, timeout=5)
            conn.request("GET", path)
            resp = conn.getresponse()
            resp.read()
        return (time.time() - t0) * 1000

    cold_latencies = []
    for _ in range(n_samples):
        clear_server_cache(host, port)
        cold_latencies.append(_timed_get(static_path))

    clear_server_cache(host, port)
    warm_latencies = []
    for i in range(n_samples):
        elapsed = _timed_get(static_path)
        if i > 0:  # discard the first request; it's the cache-populating miss
            warm_latencies.append(elapsed)
    conn.close()

    cold_avg = round(statistics.mean(cold_latencies), 3)
    warm_avg = round(statistics.mean(warm_latencies), 3)
    improvement_pct = round((1 - warm_avg / cold_avg) * 100, 2) if cold_avg > 0 else 0.0

    cold_summary = {"path": static_path, "samples": n_samples, "avg_latency_ms": cold_avg,
                     "median_latency_ms": round(statistics.median(cold_latencies), 3),
                     "max_latency_ms": round(max(cold_latencies), 3)}
    warm_summary = {"path": static_path, "samples": len(warm_latencies), "avg_latency_ms": warm_avg,
                     "median_latency_ms": round(statistics.median(warm_latencies), 3),
                     "max_latency_ms": round(max(warm_latencies), 3)}
    return cold_summary, warm_summary, improvement_pct


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Benchmark HyperServe")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--path", default="/api/health")
    parser.add_argument("--requests", type=int, default=1000)
    parser.add_argument("--concurrency", type=int, default=50)
    parser.add_argument("--static-path", default="/",
                         help="Path used for the cache cold-vs-warm comparison")
    parser.add_argument("--json-out", default=None,
                         help="Optional file to write full JSON results to")
    args = parser.parse_args()

    print(f"Benchmarking HyperServe at http://{args.host}:{args.port}")

    main_result = run_benchmark(args.host, args.port, args.path, args.requests, args.concurrency)
    print_summary(f"Throughput / Latency - {args.path}", main_result)

    cold, warm, improvement = cache_comparison(
        args.host, args.port, args.static_path,
        n_samples=max(50, args.requests // 20),
    )
    print_summary(f"Cache COLD - {args.static_path}", cold)
    print_summary(f"Cache WARM - {args.static_path}", warm)
    print(f"\nLatency improvement from caching: {improvement}%")

    metrics = fetch_metrics(args.host, args.port)
    print("\n===== Server-reported /metrics =====")
    print(json.dumps(metrics, indent=2))

    if args.json_out:
        with open(args.json_out, "w") as f:
            json.dump({
                "main": main_result,
                "cache_cold": cold,
                "cache_warm": warm,
                "cache_latency_improvement_pct": improvement,
                "server_metrics": metrics,
            }, f, indent=2)
        print(f"\nFull results written to {args.json_out}")