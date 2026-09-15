import json
import unittest

from fake_catalog import FakeItemCatalog
from fake_fetcher import FakeFetcher

from ycappuccino.api.endpoints_storage import CrudError, Forbidden, InvalidRequest, NotAuthenticated, NotFound
from ycappuccino.client.remote_crud import RemoteCrud
from ycappuccino.client.transport import HttpTransport

ALICE = {"sub": "alice", "tid": "acme"}


class TestRemoteCrud(unittest.IsolatedAsyncioTestCase):
    async def _crud(self, routes):
        fetcher = FakeFetcher(routes)
        transport = HttpTransport(fetcher=fetcher)
        await transport.start()
        catalog = FakeItemCatalog({"book": "books"})
        return RemoteCrud(transport, catalog), fetcher

    async def test_get_one_resolves_the_plural_and_returns_the_document(self):
        crud, fetcher = await self._crud({("GET", "/api/crud/books/dune"): (200, {"_id": "dune", "title": "Dune"})})

        document = await crud.get_one("book", "dune")

        self.assertEqual(document, {"_id": "dune", "title": "Dune"})
        method, url, _, body = fetcher.calls[0]
        self.assertEqual(method, "GET")
        self.assertEqual(url, "/api/crud/books/dune")
        self.assertIsNone(body)

    async def test_get_many_returns_items_and_total_from_meta_size(self):
        items = [{"_id": "dune"}, {"_id": "solaris"}]
        crud, _ = await self._crud({("GET", "/api/crud/books"): (200, items, {"type": "array", "size": 57})})

        result = await crud.get_many("book")

        self.assertEqual(result, {"items": items, "total": 57})

    async def test_create_posts_the_fields_as_json_body(self):
        crud, fetcher = await self._crud({("POST", "/api/crud/books"): (201, {"_id": "dune", "title": "Dune"})})

        document = await crud.create("book", {"title": "Dune"})

        self.assertEqual(document, {"_id": "dune", "title": "Dune"})
        method, _, headers, body = fetcher.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(json.loads(body), {"title": "Dune"})
        self.assertEqual(headers["Content-Type"], "application/json")

    async def test_update_puts_the_fields(self):
        crud, fetcher = await self._crud({("PUT", "/api/crud/books/dune"): (200, {"_id": "dune", "pages": 999})})

        document = await crud.update("book", "dune", {"pages": 999})

        self.assertEqual(document, {"_id": "dune", "pages": 999})
        method, _, _, body = fetcher.calls[0]
        self.assertEqual(method, "PUT")
        self.assertEqual(json.loads(body), {"pages": 999})

    async def test_delete_calls_the_route_and_returns_none(self):
        crud, fetcher = await self._crud({("DELETE", "/api/crud/books/dune"): (200, {})})

        result = await crud.delete("book", "dune")

        self.assertIsNone(result)
        method, url, _, _ = fetcher.calls[0]
        self.assertEqual(method, "DELETE")
        self.assertEqual(url, "/api/crud/books/dune")

    async def test_delete_many_returns_the_deleted_count(self):
        crud, fetcher = await self._crud({("DELETE", "/api/crud/books"): (200, {"deleted": 3})})

        count = await crud.delete_many("book", {"pages": {"$lt": 100}})

        self.assertEqual(count, 3)
        self.assertIn("filter=", fetcher.calls[0][1])

    async def test_a_subject_argument_is_silently_ignored_not_forwarded(self):
        """see remote_crud.py's docstring (design spec A.1): subject exists only for ICrud
        signature parity, its value is never sent to the server nor inspected"""
        crud, fetcher = await self._crud({("GET", "/api/crud/books/dune"): (200, {"_id": "dune"})})

        await crud.get_one("book", "dune", subject=ALICE)

        _, _, headers, body = fetcher.calls[0]
        self.assertNotIn("alice", json.dumps(headers))
        self.assertIsNone(body)

    async def test_401_raises_not_authenticated(self):
        crud, _ = await self._crud({("GET", "/api/crud/books/dune"): (401, {"error": "no subject"})})
        with self.assertRaises(NotAuthenticated):
            await crud.get_one("book", "dune")

    async def test_403_raises_forbidden(self):
        crud, _ = await self._crud({("GET", "/api/crud/books/dune"): (403, {"error": "forbidden"})})
        with self.assertRaises(Forbidden):
            await crud.get_one("book", "dune")

    async def test_404_raises_not_found(self):
        crud, _ = await self._crud({("GET", "/api/crud/books/dune"): (404, {"error": "not found"})})
        with self.assertRaises(NotFound):
            await crud.get_one("book", "dune")

    async def test_400_raises_invalid_request(self):
        crud, _ = await self._crud({("POST", "/api/crud/books"): (400, {"error": "invalid"})})
        with self.assertRaises(InvalidRequest):
            await crud.create("book", {})

    async def test_500_raises_generic_crud_error(self):
        crud, _ = await self._crud({("GET", "/api/crud/books/dune"): (500, {"error": "internal error"})})
        with self.assertRaises(CrudError):
            await crud.get_one("book", "dune")


if __name__ == "__main__":
    unittest.main()
