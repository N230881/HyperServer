"""
http_parser.py
---------------
Parses a raw HTTP/1.1 request (bytes straight off the socket) into a
structured HTTPRequest object. No external HTTP library is used -
this is the "implement socket handling / parsing yourself" piece
called out in the handbook's Originality Checklist.
"""

from urllib.parse import urlparse, parse_qs


class HTTPRequest:
    def __init__(self, method, path, query, http_version, headers, body, raw_size=0):
        self.method = method
        self.path = path
        self.query = query          # dict of query-string params
        self.http_version = http_version
        self.headers = headers      # dict, lower-cased keys
        self.body = body            # bytes
        self.raw_size = raw_size

    def json(self):
        import json
        if not self.body:
            return None
        return json.loads(self.body.decode("utf-8"))

    def __repr__(self):
        return f"<HTTPRequest {self.method} {self.path}>"


class HTTPParseError(Exception):
    pass


def parse_request(raw_data: bytes) -> HTTPRequest:
    """
    raw_data: full bytes read from the socket (headers + body).
    Returns an HTTPRequest, or raises HTTPParseError on malformed input.
    """
    if not raw_data:
        raise HTTPParseError("Empty request")

    try:
        header_part, _, body = raw_data.partition(b"\r\n\r\n")
        lines = header_part.decode("iso-8859-1").split("\r\n")

        request_line = lines[0]
        parts = request_line.split(" ")
        if len(parts) != 3:
            raise HTTPParseError(f"Malformed request line: {request_line}")

        method, full_path, version = parts
        parsed_url = urlparse(full_path)
        path = parsed_url.path
        query = {k: v[0] for k, v in parse_qs(parsed_url.query).items()}

        headers = {}
        for line in lines[1:]:
            if not line.strip():
                continue
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            headers[key.strip().lower()] = value.strip()

        return HTTPRequest(
            method=method.upper(),
            path=path,
            query=query,
            http_version=version,
            headers=headers,
            body=body,
            raw_size=len(raw_data),
        )
    except HTTPParseError:
        raise
    except Exception as exc:
        raise HTTPParseError(f"Failed to parse request: {exc}")
