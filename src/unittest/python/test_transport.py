import json
import unittest

from fake_fetcher import FakeFetcher

from ycappuccino.api.endpoints_storage import CrudError, Forbidden, InvalidRequest, NotAuthenticated, NotFound
from ycappuccino.client.transport import HttpTransport, ISession, RawResponse, decode_envelope


class FakeConfiguration:
    def __init__(self, values):
        self._values = values

    def get(self, key, default):
        return self._values.get(key, default)


class TestHttpTransportBaseUrl(unittest.IsolatedAsyncioTestCase):
    async def test_defaults_to_slash_api_without_a_configuration(self):
        fetcher = FakeFetcher({("GET", "/api/items"): (200, [])})
        transport = HttpTransport(configuration=None, fetcher=fetcher)
        await transport.start()

        await transport.request("GET", "/items")

        self.assertEqual(fetcher.calls[0][1], "/api/items")

    async def test_reads_client_base_url_from_configuration_at_start(self):
        fetcher = FakeFetcher({("GET", "http://localhost:9000/api/items"): (200, [])})
        configuration = FakeConfiguration({"client.base_url": "http://localhost:9000/api"})
        transport = HttpTransport(configuration=configuration, fetcher=fetcher)
        await transport.start()

        await transport.request("GET", "/items")

        self.assertEqual(fetcher.calls[0][1], "http://localhost:9000/api/items")


class TestHttpTransportRequests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fetcher = FakeFetcher(
            {
                ("GET", "/api/crud/books"): (200, [{"_id": "dune"}], {"type": "array", "size": 1}),
                ("POST", "/api/crud/books"): (201, {"_id": "dune"}),
            }
        )
        self.transport = HttpTransport(fetcher=self.fetcher)
        await self.transport.start()

    async def test_query_params_are_json_encoded_when_dict_or_list(self):
        await self.transport.request("GET", "/crud/books", params={"filter": {"pages": {"$gte": 400}}, "limit": 5})

        _, url, _, _ = self.fetcher.calls[0]
        from urllib.parse import parse_qs

        query = parse_qs(url.split("?", 1)[1])
        self.assertEqual(json.loads(query["filter"][0]), {"pages": {"$gte": 400}})
        self.assertEqual(query["limit"][0], "5")

    async def test_body_is_json_encoded_with_content_type(self):
        await self.transport.request("POST", "/crud/books", body={"title": "Dune"})

        _, _, headers, body = self.fetcher.calls[0]
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(json.loads(body), {"title": "Dune"})

    async def test_no_authorization_header_without_a_token(self):
        await self.transport.request("GET", "/crud/books")

        _, _, headers, _ = self.fetcher.calls[0]
        self.assertNotIn("Authorization", headers)

    async def test_token_is_sent_as_a_bearer_authorization_header(self):
        self.transport.set_token("demo")

        await self.transport.request("GET", "/crud/books")

        _, _, headers, _ = self.fetcher.calls[0]
        self.assertEqual(headers["Authorization"], "Bearer demo")

    async def test_clear_token_removes_the_header(self):
        self.transport.set_token("demo")
        self.transport.clear_token()

        await self.transport.request("GET", "/crud/books")

        _, _, headers, _ = self.fetcher.calls[0]
        self.assertNotIn("Authorization", headers)

    async def test_get_token_returns_the_current_token(self):
        self.assertIsNone(self.transport.get_token())
        self.transport.set_token("demo")
        self.assertEqual(self.transport.get_token(), "demo")


class TestHttpTransportDispatch(unittest.IsolatedAsyncioTestCase):
    DISPATCH = "/api/services/__remote_dispatch__/pkg.IInventory/check"

    async def test_posts_the_kwargs_to_remote_dispatch_and_returns_the_result(self):
        fetcher = FakeFetcher({("POST", self.DISPATCH): (200, {"result": 42})})
        transport = HttpTransport(fetcher=fetcher)
        await transport.start()

        result = await transport.dispatch("pkg.IInventory", "check", {"sku": "widget"})

        self.assertEqual(result, 42)
        _, _, headers, body = fetcher.calls[0]
        self.assertEqual(json.loads(body), {"kwargs": {"sku": "widget"}})
        self.assertNotIn("Authorization", headers)

    async def test_carries_the_session_token(self):
        fetcher = FakeFetcher({("POST", self.DISPATCH): (200, {"result": None})})
        transport = HttpTransport(fetcher=fetcher)
        transport.set_token("eyJ")

        await transport.dispatch("pkg.IInventory", "check", {})

        self.assertEqual(fetcher.calls[0][2]["Authorization"], "Bearer eyJ")

    async def test_a_refused_call_raises_the_matching_error(self):
        fetcher = FakeFetcher({("POST", self.DISPATCH): (403, {"error": "call pkg.IInventory.check is not authorized"})})
        transport = HttpTransport(fetcher=fetcher)

        with self.assertRaises(Forbidden):
            await transport.dispatch("pkg.IInventory", "check", {})

    def test_the_transport_is_the_session(self):
        self.assertTrue(issubclass(HttpTransport, ISession))


class TestHttpTransportWithoutFetcherFallsBackToPyodide(unittest.IsolatedAsyncioTestCase):
    async def test_fails_clearly_outside_pyodide(self):
        transport = HttpTransport()
        await transport.start()

        with self.assertRaises(RuntimeError) as raised:
            await transport.request("GET", "/items")
        self.assertIn("pyodide", str(raised.exception).lower())


class TestDecodeEnvelope(unittest.TestCase):
    def test_success_returns_the_full_envelope(self):
        body = json.dumps({"status": 200, "meta": {"type": "object", "size": 1}, "data": {"_id": "dune"}}).encode()

        envelope = decode_envelope(RawResponse(status=200, body=body))

        self.assertEqual(envelope["data"], {"_id": "dune"})

    def test_401_raises_not_authenticated(self):
        body = json.dumps({"status": 401, "meta": {}, "data": {"error": "no subject"}}).encode()
        with self.assertRaises(NotAuthenticated) as raised:
            decode_envelope(RawResponse(status=401, body=body))
        self.assertEqual(str(raised.exception), "no subject")

    def test_403_raises_forbidden(self):
        body = json.dumps({"status": 403, "meta": {}, "data": {"error": "forbidden"}}).encode()
        with self.assertRaises(Forbidden):
            decode_envelope(RawResponse(status=403, body=body))

    def test_404_raises_not_found(self):
        body = json.dumps({"status": 404, "meta": {}, "data": {"error": "not found"}}).encode()
        with self.assertRaises(NotFound):
            decode_envelope(RawResponse(status=404, body=body))

    def test_400_raises_invalid_request(self):
        body = json.dumps({"status": 400, "meta": {}, "data": {"error": "bad filter"}}).encode()
        with self.assertRaises(InvalidRequest):
            decode_envelope(RawResponse(status=400, body=body))

    def test_500_raises_generic_crud_error(self):
        body = json.dumps({"status": 500, "meta": {}, "data": {"error": "internal error"}}).encode()
        with self.assertRaises(CrudError):
            decode_envelope(RawResponse(status=500, body=body))


if __name__ == "__main__":
    unittest.main()
