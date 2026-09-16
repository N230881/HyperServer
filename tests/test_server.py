"""
tests/test_server.py
---------------------
Unit tests for the parser, LRU cache, and router - run with:
    python -m unittest tests/test_server.py -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.http_parser import parse_request, HTTPParseError
from server.lru_cache import LRUCache
from server.router import Router
from server.response import text_response, error_response


class TestHTTPParser(unittest.TestCase):
    def test_parses_get_request(self):
        raw = b"GET /hello?name=world HTTP/1.1\r\nHost: localhost\r\n\r\n"
        req = parse_request(raw)
        self.assertEqual(req.method, "GET")
        self.assertEqual(req.path, "/hello")
        self.assertEqual(req.query, {"name": "world"})
        self.assertEqual(req.headers["host"], "localhost")

    def test_parses_post_body(self):
        body = b'{"a":1}'
        raw = (b"POST /api/echo HTTP/1.1\r\nContent-Length: " +
               str(len(body)).encode() + b"\r\n\r\n" + body)
        req = parse_request(raw)
        self.assertEqual(req.method, "POST")
        self.assertEqual(req.json(), {"a": 1})

    def test_empty_request_raises(self):
        with self.assertRaises(HTTPParseError):
            parse_request(b"")

    def test_malformed_request_line_raises(self):
        with self.assertRaises(HTTPParseError):
            parse_request(b"GARBAGE\r\n\r\n")


class TestLRUCache(unittest.TestCase):
    def test_basic_put_get(self):
        cache = LRUCache(capacity=2)
        cache.put("a", 1)
        cache.put("b", 2)
        self.assertEqual(cache.get("a"), 1)
        self.assertEqual(cache.get("z"), None)

    def test_eviction_order(self):
        cache = LRUCache(capacity=2)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.get("a")          # 'a' becomes most-recently-used
        cache.put("c", 3)       # should evict 'b' (least recently used)
        self.assertIsNone(cache.get("b"))
        self.assertEqual(cache.get("a"), 1)
        self.assertEqual(cache.get("c"), 3)

    def test_hit_miss_stats(self):
        cache = LRUCache(capacity=5)
        cache.put("x", 10)
        cache.get("x")
        cache.get("y")
        stats = cache.stats()
        self.assertEqual(stats["hits"], 1)
        self.assertEqual(stats["misses"], 1)


class TestRouter(unittest.TestCase):
    def setUp(self):
        self.router = Router()

        @self.router.get("/hello")
        def hello(request):
            return text_response("hi")

        @self.router.get("/users/<user_id>")
        def get_user(request, user_id):
            return text_response(f"user-{user_id}")

    def test_static_route_resolves(self):
        handler, params = self.router.resolve("GET", "/hello")
        self.assertIsNotNone(handler)
        self.assertEqual(params, {})

    def test_dynamic_route_resolves(self):
        handler, params = self.router.resolve("GET", "/users/42")
        self.assertIsNotNone(handler)
        self.assertEqual(params, {"user_id": "42"})

    def test_unknown_route_returns_none(self):
        handler, params = self.router.resolve("GET", "/nope")
        self.assertIsNone(handler)

    def test_middleware_chain_runs(self):
        order = []

        def mw1(req, nxt):
            order.append("mw1-before")
            resp = nxt(req)
            order.append("mw1-after")
            return resp

        def mw2(req, nxt):
            order.append("mw2-before")
            resp = nxt(req)
            order.append("mw2-after")
            return resp

        self.router.use(mw1)
        self.router.use(mw2)

        class FakeReq:
            method = "GET"
            path = "/hello"

        self.router.dispatch(FakeReq())
        self.assertEqual(order, ["mw1-before", "mw2-before", "mw2-after", "mw1-after"])


if __name__ == "__main__":
    unittest.main()
