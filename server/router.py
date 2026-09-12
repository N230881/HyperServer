"""
router.py
---------
HashMap-based routing (method + path -> handler), with support for
dynamic path segments like /users/<id>, and a middleware chain that
wraps every request (logging, security, rate limiting, etc.).

DSA mapping: routes are stored in a dict keyed by method -> {path: handler},
giving O(1) average lookup for static routes; dynamic routes fall back to
a linear scan + segment matching (small N in practice, documented tradeoff).
"""

from server.response import error_response


class Router:
    def __init__(self):
        # {"GET": {"/path": handler}, ...}
        self.static_routes = {}
        # {"GET": [(segments, handler), ...]}
        self.dynamic_routes = {}
        self.middlewares = []  # list of callables: (request, next_fn) -> HTTPResponse

    def use(self, middleware_fn):
        """Register a middleware. Middlewares run in registration order."""
        self.middlewares.append(middleware_fn)

    def _register(self, method, path, handler):
        method = method.upper()
        if "<" in path:
            segments = path.strip("/").split("/")
            self.dynamic_routes.setdefault(method, []).append((segments, handler))
        else:
            self.static_routes.setdefault(method, {})[path] = handler

    def get(self, path):
        def decorator(fn):
            self._register("GET", path, fn)
            return fn
        return decorator

    def post(self, path):
        def decorator(fn):
            self._register("POST", path, fn)
            return fn
        return decorator

    def put(self, path):
        def decorator(fn):
            self._register("PUT", path, fn)
            return fn
        return decorator

    def delete(self, path):
        def decorator(fn):
            self._register("DELETE", path, fn)
            return fn
        return decorator

    def _match_dynamic(self, method, path):
        candidates = self.dynamic_routes.get(method, [])
        req_segments = path.strip("/").split("/")
        for segments, handler in candidates:
            if len(segments) != len(req_segments):
                continue
            params = {}
            matched = True
            for seg, req_seg in zip(segments, req_segments):
                if seg.startswith("<") and seg.endswith(">"):
                    params[seg[1:-1]] = req_seg
                elif seg != req_seg:
                    matched = False
                    break
            if matched:
                return handler, params
        return None, None

    def resolve(self, method, path):
        """Returns (handler, params) or (None, None) if no route matches."""
        method = method.upper()
        handler = self.static_routes.get(method, {}).get(path)
        if handler:
            return handler, {}
        return self._match_dynamic(method, path)

    def dispatch(self, request):
        """
        Runs the full middleware chain, then the matched route handler.
        Middleware signature: middleware(request, next_fn) -> HTTPResponse
        """
        handler, params = self.resolve(request.method, request.path)

        def final_handler(req):
            if handler is None:
                return error_response(404, f"No route for {req.method} {req.path}")
            try:
                return handler(req, **params)
            except TypeError as e:
                return error_response(400, f"Bad request parameters: {e}")
            except Exception as e:
                return error_response(500, f"Internal error: {e}")

        # build the chain: middleware[0] wraps middleware[1] wraps ... wraps final_handler
        chain = final_handler
        for mw in reversed(self.middlewares):
            chain = _bind(mw, chain)

        return chain(request)


def _bind(middleware_fn, next_in_chain):
    def wrapped(req):
        return middleware_fn(req, next_in_chain)
    return wrapped
