"""
middleware.py
-------------
Reusable middleware functions. Each middleware has the signature
    def middleware(request, next_fn) -> HTTPResponse
and must call next_fn(request) to continue the chain (or short-circuit
by returning its own response, e.g. for rate limiting / auth).
"""

import time
import threading
from collections import defaultdict, deque

from server.response import error_response


def timing_middleware(request, next_fn):
    """Attaches request timing; stored on the request object for the logger."""
    start = time.time()
    response = next_fn(request)
    request._duration_ms = (time.time() - start) * 1000
    return response


def security_headers_middleware(request, next_fn):
    """Extra per-response hardening beyond the defaults in response.py."""
    response = next_fn(request)
    response.headers.setdefault("X-Powered-By", "HyperServe")
    response.headers.setdefault("Cache-Control", "no-store" if request.method != "GET" else "public, max-age=30")
    return response


class RateLimiter:
    """
    Simple sliding-window rate limiter, keyed by client IP.
    Demonstrates a queue-per-client + synchronization, per the DSA mapping.
    """

    def __init__(self, max_requests=100, window_seconds=60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._history = defaultdict(deque)
        self._lock = threading.Lock()

    def middleware(self, request, next_fn):
        client_ip = request.headers.get("x-client-ip", "unknown")
        now = time.time()
        with self._lock:
            dq = self._history[client_ip]
            while dq and now - dq[0] > self.window_seconds:
                dq.popleft()
            if len(dq) >= self.max_requests:
                return error_response(429, "Rate limit exceeded. Try again later.")
            dq.append(now)
        return next_fn(request)
