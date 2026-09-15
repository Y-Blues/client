import unittest

from fake_fetcher import FakeFetcher

from ycappuccino.api.endpoints_storage import NotFound
from ycappuccino.client.remote_item_catalog import RemoteItemCatalog
from ycappuccino.client.transport import HttpTransport

BOOK = {
    "id": "book", "plural": "books", "app": "library", "module": "library.books",
    "secure_read": False, "secure_write": False, "writable": True, "multipart": False, "refs": [],
}


class TestRemoteItemCatalog(unittest.IsolatedAsyncioTestCase):
    async def _catalog(self, extra_routes=None):
        routes = {("GET", "/api/items"): (200, [BOOK], {"type": "array", "size": 1})}
        routes.update(extra_routes or {})
        fetcher = FakeFetcher(routes)
        transport = HttpTransport(fetcher=fetcher)
        await transport.start()
        catalog = RemoteItemCatalog(transport)
        await catalog.start()
        return catalog, fetcher

    async def test_get_items_returns_the_cached_list_fetched_at_start(self):
        catalog, fetcher = await self._catalog()

        items = await catalog.get_items()

        self.assertEqual(items, [BOOK])
        self.assertEqual(len(fetcher.calls), 1)  # start() only; get_items() does not refetch

    async def test_get_item_resolves_from_the_cache(self):
        catalog, fetcher = await self._catalog()

        item = await catalog.get_item("book")

        self.assertEqual(item, BOOK)
        self.assertEqual(len(fetcher.calls), 1)

    async def test_get_item_raises_not_found_for_an_unknown_id(self):
        catalog, _ = await self._catalog()

        with self.assertRaises(NotFound):
            await catalog.get_item("unknown")

    async def test_get_item_by_plural_resolves_from_the_cache(self):
        catalog, _ = await self._catalog()

        item = await catalog.get_item_by_plural("books")

        self.assertEqual(item, BOOK)

    async def test_get_item_by_plural_raises_not_found_for_an_unknown_plural(self):
        catalog, _ = await self._catalog()

        with self.assertRaises(NotFound):
            await catalog.get_item_by_plural("unknown")

    async def test_get_schema_fetches_by_resolved_plural(self):
        catalog, fetcher = await self._catalog({("GET", "/api/items/books/schema"): (200, {"type": "object"})})

        schema = await catalog.get_schema("book")

        self.assertEqual(schema, {"type": "object"})
        self.assertEqual(fetcher.calls[-1][1], "/api/items/books/schema")

    async def test_get_empty_fetches_by_resolved_plural(self):
        catalog, fetcher = await self._catalog({("GET", "/api/items/books/empty"): (200, {"title": None})})

        empty = await catalog.get_empty("book")

        self.assertEqual(empty, {"title": None})
        self.assertEqual(fetcher.calls[-1][1], "/api/items/books/empty")


if __name__ == "__main__":
    unittest.main()
