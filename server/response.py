"""
response.py
-----------
Builds raw HTTP/1.1 response byte streams, including the security
headers called out in the handbook's Technical Excellence section.
"""

import json
from datetime import datetime, timezone

STATUS_TEXT = {
    200: "OK", 201: "Created", 204: "No Content",
    301: "Moved Permanently", 302: "Found",
    400: "Bad Request", 401: "Unauthorized", 403: "Forbidden",
    404: "Not Found", 405: "Method Not Allowed", 408: "Request Timeout",
    429: "Too Many Requests",
    500: "Internal Server Error", 501: "Not Implemented", 503: "Service Unavailable",
}

DEFAULT_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Server": "HyperServe/1.0",
}


class HTTPResponse:
    def __init__(self, status_code=200, headers=None, body=b""):
        self.status_code = status_code
        self.headers = headers or {}
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.body = body

    def to_bytes(self) -> bytes:
        status_text = STATUS_TEXT.get(self.status_code, "Unknown")
        headers = {**DEFAULT_SECURITY_HEADERS, **self.headers}
        headers.setdefault("Content-Length", str(len(self.body)))
        headers.setdefault("Date", datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT"))
        headers.setdefault("Connection", "close")

        lines = [f"HTTP/1.1 {self.status_code} {status_text}"]
        for k, v in headers.items():
            lines.append(f"{k}: {v}")
        head = "\r\n".join(lines) + "\r\n\r\n"
        return head.encode("utf-8") + self.body


def text_response(body: str, status_code=200, headers=None):
    h = {"Content-Type": "text/plain; charset=utf-8"}
    if headers:
        h.update(headers)
    return HTTPResponse(status_code, h, body)


def html_response(body: str, status_code=200, headers=None):
    h = {"Content-Type": "text/html; charset=utf-8"}
    if headers:
        h.update(headers)
    return HTTPResponse(status_code, h, body)


def json_response(data, status_code=200, headers=None):
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    return HTTPResponse(status_code, h, json.dumps(data, indent=2))


def file_response(content: bytes, content_type: str, status_code=200, headers=None):
    h = {"Content-Type": content_type}
    if headers:
        h.update(headers)
    return HTTPResponse(status_code, h, content)


def error_response(status_code: int, message: str = ""):
    message = message or STATUS_TEXT.get(status_code, "Error")
    return json_response({"error": message, "status_code": status_code}, status_code)