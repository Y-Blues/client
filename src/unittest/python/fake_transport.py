"""
FakeTransport: stands in for pyodide.http.pyfetch in tests, so ApiClient is testable in plain
CPython. It builds the exact JSON envelope http_server would send ({"status", "meta", "data"}),
never an already-unwrapped value, so tests exercise ApiClient's own envelope handling.
"""

import json

from ycappuccino.client.http import RawResponse


class FakeTransport:
    """
    routes: {(method, path): entry} where "path" is compared without the query string. entry is
    either (status, data) - "meta" is then inferred the same way http_server infers it ("array"
    with "size": len(data) for a list, "object" with "size": 1 for a dict/None, bare "object" for
    an error dict with status >= 400) - or (status, data, meta) to control "meta" explicitly, e.g.
    to simulate a "total" that differs from len(items) (pagination).
    """

    def __init__(self, routes):
        self._routes = routes
        self.calls = []

    async def __call__(self, method, url, headers, body):
        self.calls.append((method, url, dict(headers), body))
        path = url.split("?", 1)[0]
        key = (method, path)
        if key not in self._routes:
            raise AssertionError(f"FakeTransport: no route for {method} {path}")
        entry = self._routes[key]
        status, data = entry[0], entry[1]
        if len(entry) > 2:
            meta = entry[2]
        elif isinstance(data, list):
            meta = {"type": "array", "size": len(data)}
        elif isinstance(data, dict) and "error" in data and status >= 400:
            meta = {"type": "object"}
        else:
            meta = {"type": "object", "size": 1}
        envelope = {"status": status, "meta": meta, "data": data}
        return RawResponse(status=status, headers={}, body=json.dumps(envelope).encode())
