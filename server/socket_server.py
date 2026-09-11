"""
socket_server.py
-----------------
Raw TCP socket listener. Accepts connections on the main thread and
hands each one off to the ThreadPool for concurrent processing -
this is the "Single-threaded -> Thread Pool" upgrade from the handbook.
"""

import socket
import threading
import time

from server.thread_pool import ThreadPool
from server.http_parser import parse_request, HTTPParseError
from server.response import error_response
from server.logger import log_request

RECV_CHUNK = 8192
MAX_REQUEST_BYTES = 5 * 1024 * 1024  # 5 MB safety cap


class HyperServeServer:
    def __init__(self, router, host="127.0.0.1", port=8080, num_threads=8):
        self.router = router
        self.host = host
        self.port = port
        self.num_threads = num_threads
        self.server_socket = None
        self._running = False
        self.start_time = None
        self.total_requests = 0
        self._counter_lock = threading.Lock()

        self.pool = ThreadPool(num_threads, self._handle_connection)

    # ---------- connection handling ----------

    def _recv_full_request(self, conn) -> bytes:
        """
        Reads until it sees the end of headers (\\r\\n\\r\\n), then reads
        the exact Content-Length body if present. Handles requests that
        arrive in multiple TCP packets.
        """
        conn.settimeout(5)
        data = b""
        while b"\r\n\r\n" not in data:
            try:
                chunk = conn.recv(RECV_CHUNK)
            except socket.timeout:
                if data:
                    # We got *some* bytes but the client stalled mid-request -
                    # that's a genuine timeout worth reporting as 408.
                    raise
                # Nothing was ever sent on this connection (browsers commonly
                # pre-open idle/speculative sockets). Treat as a no-op, not
                # an error.
                return b""
            if not chunk:
                break
            data += chunk
            if len(data) > MAX_REQUEST_BYTES:
                raise HTTPParseError("Request too large")

        if not data:
            return b""

        header_part, sep, body_part = data.partition(b"\r\n\r\n")
        content_length = 0
        for line in header_part.decode("iso-8859-1").split("\r\n")[1:]:
            if line.lower().startswith("content-length:"):
                content_length = int(line.split(":", 1)[1].strip())
                break

        while len(body_part) < content_length:
            try:
                chunk = conn.recv(RECV_CHUNK)
            except socket.timeout:
                raise
            if not chunk:
                break
            body_part += chunk

        return header_part + sep + body_part

    def _wants_keep_alive(self, request) -> bool:
        """
        HTTP/1.1 defaults to persistent connections unless the client sends
        'Connection: close'. HTTP/1.0 defaults to close unless the client
        explicitly asks for 'Connection: keep-alive'.
        """
        conn_header = request.headers.get("connection", "").lower()
        if conn_header == "close":
            return False
        if request.http_version.upper() == "HTTP/1.1":
            return conn_header != "close"
        return conn_header == "keep-alive"

    def _handle_connection(self, conn, addr):
        thread_name = threading.current_thread().name
        keep_alive = True
        requests_served = 0
        MAX_REQUESTS_PER_CONN = 100  # safety cap against a single client hogging a thread

        while keep_alive and requests_served < MAX_REQUESTS_PER_CONN:
            start = time.time()
            method, path, status_code, cache_hit = "-", "-", 500, False
            skip_logging = False
            keep_alive = False  # only re-enabled below if the request asks for it

            try:
                raw = self._recv_full_request(conn)
                if not raw:
                    # Idle/speculative connection, or the client closed a
                    # previously kept-alive connection. Either way, nothing
                    # new to log.
                    skip_logging = True
                    break
                request = parse_request(raw)
                request.client_addr = addr
                request._duration_ms = 0
                request._cache_hit = False

                method, path = request.method, request.path
                keep_alive = self._wants_keep_alive(request)

                response = self.router.dispatch(request)
                status_code = response.status_code
                cache_hit = getattr(request, "_cache_hit", False)

                response.headers["Connection"] = "keep-alive" if keep_alive else "close"
                conn.sendall(response.to_bytes())

            except HTTPParseError as e:
                status_code = 400
                conn.sendall(error_response(400, str(e)).to_bytes())
            except (ConnectionResetError, BrokenPipeError, socket.timeout):
                status_code = 408
            except Exception as e:
                status_code = 500
                try:
                    conn.sendall(error_response(500, str(e)).to_bytes())
                except Exception:
                    pass
            finally:
                if not skip_logging:
                    duration_ms = (time.time() - start) * 1000
                    with self._counter_lock:
                        self.total_requests += 1
                    log_request(method, path, status_code, duration_ms, addr,
                                cache_hit=cache_hit, thread_name=thread_name)
                requests_served += 1

        try:
            conn.close()
        except Exception:
            pass

    # ---------- server lifecycle ----------

    def start(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(128)
        self._running = True
        self.start_time = time.time()

        print(f"HyperServe listening on http://{self.host}:{self.port}")
        print(f"Thread pool size: {self.num_threads}")

        try:
            while self._running:
                try:
                    self.server_socket.settimeout(1.0)
                    conn, addr = self.server_socket.accept()
                    self.pool.submit(conn, addr)
                except socket.timeout:
                    continue
        except KeyboardInterrupt:
            print("\nShutting down HyperServe...")
        finally:
            self.stop()

    def stop(self):
        self._running = False
        self.pool.shutdown()
        if self.server_socket:
            self.server_socket.close()

    def stats(self):
        uptime = time.time() - self.start_time if self.start_time else 0
        return {
            "uptime_seconds": round(uptime, 1),
            "total_requests": self.total_requests,
            "requests_per_sec": round(self.total_requests / uptime, 2) if uptime > 0 else 0,
            "thread_pool": self.pool.stats(),
        }