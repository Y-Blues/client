import json
import unittest

from fake_transport import FakeTransport

from ycappuccino.api.endpoints_storage import CrudError, Forbidden, InvalidRequest, NotAuthenticated, NotFound
from ycappuccino.client.http import ApiClient


class TestApiClientCrud(unittest.IsolatedAsyncioTestCase):
    async def test_get_one_calls_the_crud_route_and_returns_the_document(self):
        transport = FakeTransport({("GET", "http://api/api/crud/books/dune"): (200, {"_id": "dune", "title": "Dune"})})
        client = ApiClient("http://api", transport=transport)

        document = await client.get_one("books", "dune")

        self.assertEqual(document, {"_id": "dune", "title": "Dune"})
        method, url, headers, body = transport.calls[0]
        self.assertEqual(method, "GET")
        self.assertEqual(url, "http://api/api/crud/books/dune")
        self.assertIsNone(body)

    async def test_get_many_returns_items_and_total_from_meta_size(self):
        items = [{"_id": "dune"}, {"_id": "solaris"}]
        transport = FakeTransport(
            {("GET", "http://api/api/crud/books"): (200, items, {"type": "array", "size": 57})}
        )
        client = ApiClient("http://api", transport=transport)

        result = await client.get_many("books")

        self.assertEqual(result, {"items": items, "total": 57})

    async def test_get_many_encodes_dict_params_as_json_in_the_query_string(self):
        transport = FakeTransport({("GET", "http://api/api/crud/books"): (200, [], {"type": "array", "size": 0})})
        client = ApiClient("http://api", transport=transport)

        await client.get_many("books", {"filter": {"pages": {"$gte": 400}}, "limit": 5})

        _, url, _, _ = transport.calls[0]
        from urllib.parse import parse_qs

        query = url.split("?", 1)[1]
        params = parse_qs(query)

        self.assertEqual(json.loads(params["filter"][0]), {"pages": {"$gte": 400}})
        self.assertEqual(params["limit"][0], "5")

    async def test_create_posts_the_fields_as_json_body(self):
        transport = FakeTransport({("POST", "http://api/api/crud/books"): (201, {"_id": "dune", "title": "Dune"})})
        client = ApiClient("http://api", transport=transport)

        document = await client.create("books", {"title": "Dune"})

        self.assertEqual(document, {"_id": "dune", "title": "Dune"})
        method, url, headers, body = transport.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(json.loads(body), {"title": "Dune"})
        self.assertEqual(headers["Content-Type"], "application/json")

    async def test_update_puts_the_fields(self):
        transport = FakeTransport({("PUT", "http://api/api/crud/books/dune"): (200, {"_id": "dune", "pages": 999})})
        client = ApiClient("http://api", transport=transport)

        document = await client.update("books", "dune", {"pages": 999})

        self.assertEqual(document, {"_id": "dune", "pages": 999})
        method, url, headers, body = transport.calls[0]
        self.assertEqual(method, "PUT")
        self.assertEqual(json.loads(body), {"pages": 999})

    async def test_delete_calls_the_route_and_returns_nothing(self):
        transport = FakeTransport({("DELETE", "http://api/api/crud/books/dune"): (200, {})})
        client = ApiClient("http://api", transport=transport)

        result = await client.delete("books", "dune")

        self.assertIsNone(result)
        method, url, headers, body = transport.calls[0]
        self.assertEqual(method, "DELETE")
        self.assertEqual(url, "http://api/api/crud/books/dune")

    async def test_delete_many_returns_the_deleted_count(self):
        transport = FakeTransport({("DELETE", "http://api/api/crud/books"): (200, {"deleted": 3})})
        client = ApiClient("http://api", transport=transport)

        count = await client.delete_many("books", {"pages": {"$lt": 100}})

        self.assertEqual(count, 3)
        _, url, _, _ = transport.calls[0]
        self.assertIn("filter=", url)

    async def test_call_hits_the_service_route_with_extra_path_and_returns_the_body(self):
        transport = FakeTransport({("POST", "http://api/api/services/echo/ping"): (200, {"echo": "hi"})})
        client = ApiClient("http://api", transport=transport)

        result = await client.call("echo", "POST", extra_path=["ping"], body={"echo": "hi"})

        self.assertEqual(result, {"echo": "hi"})
        method, url, headers, body = transport.calls[0]
        self.assertEqual(url, "http://api/api/services/echo/ping")
        self.assertEqual(json.loads(body), {"echo": "hi"})

    async def test_token_is_sent_as_a_bearer_authorization_header(self):
        transport = FakeTransport({("GET", "http://api/api/crud/books/dune"): (200, {"_id": "dune"})})
        client = ApiClient("http://api", transport=transport, token="demo")

        await client.get_one("books", "dune")

        _, _, headers, _ = transport.calls[0]
        self.assertEqual(headers["Authorization"], "Bearer demo")


class TestApiClientErrors(unittest.IsolatedAsyncioTestCase):
    async def test_401_raises_not_authenticated(self):
        transport = FakeTransport({("GET", "http://api/api/crud/books/dune"): (401, {"error": "no subject"})})
        client = ApiClient("http://api", transport=transport)

        with self.assertRaises(NotAuthenticated) as raised:
            await client.get_one("books", "dune")
        self.assertEqual(str(raised.exception), "no subject")

    async def test_403_raises_forbidden(self):
        transport = FakeTransport({("GET", "http://api/api/crud/books/dune"): (403, {"error": "forbidden"})})
        client = ApiClient("http://api", transport=transport)

        with self.assertRaises(Forbidden):
            await client.get_one("books", "dune")

    async def test_404_raises_not_found(self):
        transport = FakeTransport({("GET", "http://api/api/crud/books/dune"): (404, {"error": "not found"})})
        client = ApiClient("http://api", transport=transport)

        with self.assertRaises(NotFound):
            await client.get_one("books", "dune")

    async def test_400_raises_invalid_request(self):
        transport = FakeTransport({("POST", "http://api/api/crud/books"): (400, {"error": "invalid JSON body"})})
        client = ApiClient("http://api", transport=transport)

        with self.assertRaises(InvalidRequest):
            await client.create("books", {"title": "Dune"})

    async def test_500_raises_generic_crud_error(self):
        transport = FakeTransport({("GET", "http://api/api/crud/books/dune"): (500, {"error": "internal error"})})
        client = ApiClient("http://api", transport=transport)

        with self.assertRaises(CrudError):
            await client.get_one("books", "dune")


class TestApiClientDefaultTransport(unittest.IsolatedAsyncioTestCase):
    async def test_without_an_injected_transport_falls_back_to_pyodide_and_fails_clearly_outside_it(self):
        client = ApiClient("http://api")

        with self.assertRaises(RuntimeError) as raised:
            await client.get_one("books", "dune")
        self.assertIn("pyodide", str(raised.exception).lower())


if __name__ == "__main__":
    unittest.main()
