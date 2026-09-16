"""
RemoteServiceEndpoint (ycappuccino.client.components): the one interface that triggers
convention 3 (literal method/extra_path/params/body override) - its own call() parameters
already carry the HTTP verb/extra path/query/body, so no verb/path inference from the method
NAME ("call") ever happens.
"""

import json
import unittest

from fake_fetcher import FakeFetcher

from ycappuccino.api.endpoints_storage import NotFound
from ycappuccino.client.components import RemoteServiceEndpoint
from ycappuccino.client.transport import HttpTransport


class TestRemoteServiceEndpoint(unittest.IsolatedAsyncioTestCase):
    async def _endpoint(self, routes):
        fetcher = FakeFetcher(routes)
        transport = HttpTransport(fetcher=fetcher)
        await transport.start()
        return RemoteServiceEndpoint(transport), fetcher, transport

    async def test_call_hits_services_slash_name_with_the_literal_method_and_body(self):
        endpoint, fetcher, _ = await self._endpoint({("POST", "/api/services/echo"): (200, {"echo": "hi"})})

        result = await endpoint.call("echo", "POST", [], {}, {"echo": "hi"}, None)

        self.assertEqual(result.body, {"echo": "hi"})
        method, url, _, body = fetcher.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "/api/services/echo")
        self.assertEqual(json.loads(body), {"echo": "hi"})

    async def test_the_literal_method_param_is_used_even_though_the_python_method_is_named_call(self):
        """proves convention 1 (verb from method NAME) never fires here: "call" would map to
        POST by convention 1, but a literal GET method= must still produce a GET"""
        endpoint, fetcher, _ = await self._endpoint({("GET", "/api/services/echo"): (200, {"ok": True})})

        await endpoint.call("echo", "GET", [], {}, None, None)

        self.assertEqual(fetcher.calls[0][0], "GET")

    async def test_extra_path_is_appended_after_the_service_name(self):
        endpoint, fetcher, _ = await self._endpoint({("GET", "/api/services/echo/ping"): (200, {"pong": True})})

        await endpoint.call("echo", "GET", ["ping"], {}, None, None)

        self.assertEqual(fetcher.calls[0][1], "/api/services/echo/ping")

    async def test_params_are_forwarded_as_the_literal_query(self):
        endpoint, fetcher, _ = await self._endpoint({("GET", "/api/services/echo"): (200, {})})

        await endpoint.call("echo", "GET", [], {"verbose": "1"}, None, None)

        self.assertIn("verbose=1", fetcher.calls[0][1])

    async def test_a_login_call_returns_a_token_that_can_be_set_on_the_transport(self):
        """mirrors permissions_app's `login` service: POST /api/services/login -> {"token": ...}"""
        endpoint, _, transport = await self._endpoint(
            {("POST", "/api/services/login"): (200, {"token": "eyJ..."})}
        )

        result = await endpoint.call("login", "POST", [], {}, {"login": "alice", "password": "x"}, None)
        transport.set_token(result.body["token"])

        self.assertEqual(transport.get_token(), "eyJ...")

    async def test_not_found_service_raises_not_found(self):
        endpoint, _, _ = await self._endpoint({("POST", "/api/services/unknown"): (404, {"error": "not found"})})

        with self.assertRaises(NotFound):
            await endpoint.call("unknown", "POST", [], {}, None, None)


if __name__ == "__main__":
    unittest.main()
