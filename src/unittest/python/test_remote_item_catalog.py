"""
Every RemoteItemCatalog (ycappuccino.client.components) method against a fake IHttpFetcher.
IItemCatalog is convention 4's whole reason for existing: get_items() is the one real bulk fetch,
cached once at start(); get_item/get_item_by_plural are then served from that cache with NO
further HTTP call, while get_schema/get_empty still fire one live HTTP call each - this file
proves the split lands exactly where it should (spec §9.3/§9.4).
"""

import unittest

from fake_fetcher import FakeFetcher

from ycappuccino.api.endpoints_storage import NotFound
from ycappuccino.client.components import RemoteItemCatalog
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

    async def test_get_items_is_fetched_once_at_start_and_cached(self):
        catalog, fetcher = await self._catalog()

        items = await catalog.get_items()

        self.assertEqual(items, [BOOK])
        self.assertEqual(len(fetcher.calls), 1)  # start() only; get_items() does not refetch
        self.assertEqual(fetcher.calls[0][:2], ("GET", "/api/items"))

    async def test_get_item_resolves_from_the_cache_no_extra_http_call(self):
        catalog, fetcher = await self._catalog()

        item = await catalog.get_item("book")

        self.assertEqual(item, BOOK)
        self.assertEqual(len(fetcher.calls), 1)

    async def test_get_item_raises_not_found_for_an_unknown_id(self):
        catalog, _ = await self._catalog()

        with self.assertRaises(NotFound):
            await catalog.get_item("unknown")

    async def test_get_item_by_plural_resolves_from_the_cache_no_extra_http_call(self):
        catalog, fetcher = await self._catalog()

        item = await catalog.get_item_by_plural("books")

        self.assertEqual(item, BOOK)
        self.assertEqual(len(fetcher.calls), 1)

    async def test_get_item_by_plural_raises_not_found_for_an_unknown_plural(self):
        catalog, _ = await self._catalog()

        with self.assertRaises(NotFound):
            await catalog.get_item_by_plural("unknown")

    async def test_get_schema_fires_a_real_http_call_with_a_schema_suffix(self):
        catalog, fetcher = await self._catalog({("GET", "/api/items/books/schema"): (200, {"type": "object"})})

        schema = await catalog.get_schema("book")

        self.assertEqual(schema, {"type": "object"})
        self.assertEqual(fetcher.calls[-1][:2], ("GET", "/api/items/books/schema"))
        self.assertEqual(len(fetcher.calls), 2)  # start()'s bulk fetch + this one

    async def test_get_empty_fires_a_real_http_call_with_an_empty_suffix(self):
        catalog, fetcher = await self._catalog({("GET", "/api/items/books/empty"): (200, {"title": None})})

        empty = await catalog.get_empty("book")

        self.assertEqual(empty, {"title": None})
        self.assertEqual(fetcher.calls[-1][:2], ("GET", "/api/items/books/empty"))


if __name__ == "__main__":
    unittest.main()
