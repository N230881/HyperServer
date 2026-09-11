"""
main.py
-------
Entry point. Run with:

    python main.py --host 127.0.0.1 --port 8080 --threads 8

Then visit http://127.0.0.1:8080/ in a browser, or run the Streamlit
dashboard (dashboard/streamlit_app.py) in a separate terminal.
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.routes import router, build_metrics_route
from server.socket_server import HyperServeServer
from server.middleware import timing_middleware, security_headers_middleware, RateLimiter


def build_server(host, port, threads, rate_limit):
    server = HyperServeServer(router, host=host, port=port, num_threads=threads)

    # middleware order = execution order (outermost first)
    router.use(timing_middleware)
    router.use(security_headers_middleware)
    if rate_limit:
        limiter = RateLimiter(max_requests=rate_limit, window_seconds=60)
        router.use(limiter.middleware)

    build_metrics_route(server)  # registers GET /metrics
    return server


def main():
    parser = argparse.ArgumentParser(description="HyperServe - Multithreaded HTTP Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host/IP to bind")
    parser.add_argument("--port", type=int, default=8080, help="Port to bind")
    parser.add_argument("--threads", type=int, default=8, help="Thread pool size")
    parser.add_argument("--rate-limit", type=int, default=0,
                         help="Max requests/min per client (0 = disabled)")
    args = parser.parse_args()

    server = build_server(args.host, args.port, args.threads, args.rate_limit)
    server.start()


if __name__ == "__main__":
    main()
