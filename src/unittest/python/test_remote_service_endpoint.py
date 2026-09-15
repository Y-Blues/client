import json
import unittest

from fake_fetcher import FakeFetcher

from ycappuccino.api.endpoints_storage import NotFound
from ycappuccino.client.remote_service_endpoint import RemoteServiceEndpoint
from ycappuccino.client.transport import HttpTransport


class TestRemoteServiceEndpoint(unittest.IsolatedAsyncioTestCase):
    async def _endpoint(self, routes):
        fetcher = FakeFetcher(routes)
        transport = HttpTransport(fetcher=fetcher)
        await transport.start()
        return RemoteServiceEndpoint(transport), fetcher, transport

    async def test_call_hits_the_named_service_route_and_returns_the_body(self):
        endpoint, fetcher, _ = await self._endpoint({("POST", "/api/services/echo"): (200, {"echo": "hi"})})

        result = await endpoint.call("echo", "POST", [], {}, {"echo": "hi"}, None)

        self.assertEqual(result.body, {"echo": "hi"})
        method, url, _, body = fetcher.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "/api/services/echo")
        self.assertEqual(json.loads(body), {"echo": "hi"})

    async def test_extra_path_is_appended_after_the_service_name(self):
        endpoint, fetcher, _ = await self._endpoint({("GET", "/api/services/echo/ping"): (200, {"pong": True})})

        await endpoint.call("echo", "GET", ["ping"], {}, None, None)

        self.assertEqual(fetcher.calls[0][1], "/api/services/echo/ping")

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
