"""
FakeFetcher: stands in for a real ycappuccino.client.transport.IHttpFetcher in tests, so
HttpTransport (and everything built on it) is testable in plain CPython, without a real Pyodide
runtime or network. Builds the exact JSON envelope http_server would send ({"status", "meta",
"data"}), never an already-unwrapped value, so tests exercise HttpTransport/decode_envelope's own
envelope handling, not a shortcut around it.

Used two ways in this test suite: constructed directly and injected into HttpTransport(fetcher=...)
for component-level unit tests (no framework at all - see core/README.md "Tester ses composants");
and, in test_client_framework.py, as the template for an equivalent class written into a real
temporary application package, published as a genuine ycappuccino.client.transport.IHttpFetcher
component and picked up by the real framework's DI.
"""

import json

from ycappuccino.client.transport import RawResponse


class FakeFetcher:
    """
    routes: {(method, path): entry} where "path" is the URL without its query string. entry is
    either (status, data) - "meta" is then inferred the same way http_server infers it - or
    (status, data, meta) to control "meta" explicitly (e.g. a "total" that differs from
    len(items), to prove pagination isn't just len(data)).
    """

    def __init__(self, routes):
        self._routes = routes
        self.calls = []

    async def fetch(self, method, url, headers, body):
        self.calls.append((method, url, dict(headers), body))
        path = url.split("?", 1)[0]
        key = (method, path)
        if key not in self._routes:
            raise AssertionError(f"FakeFetcher: no route for {method} {path}")
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
