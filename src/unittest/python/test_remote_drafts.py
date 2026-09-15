import unittest

from fake_catalog import FakeItemCatalog
from fake_fetcher import FakeFetcher

from ycappuccino.client.remote_drafts import RemoteDrafts
from ycappuccino.client.transport import HttpTransport


class TestRemoteDrafts(unittest.IsolatedAsyncioTestCase):
    async def _drafts(self, routes):
        fetcher = FakeFetcher(routes)
        transport = HttpTransport(fetcher=fetcher)
        await transport.start()
        catalog = FakeItemCatalog({"book": "books"})
        return RemoteDrafts(transport, catalog), fetcher

    async def test_get_one_hits_the_draft_route(self):
        drafts, fetcher = await self._drafts(
            {("GET", "/api/drafts/books/dune/review"): (200, {"_id": "dune", "_draft": "review"})}
        )

        document = await drafts.get_one("book", "dune", "review")

        self.assertEqual(document["_draft"], "review")
        self.assertEqual(fetcher.calls[0][1], "/api/drafts/books/dune/review")

    async def test_get_many_hits_the_plural_draft_route(self):
        items = [{"_id": "dune", "_draft": "review"}]
        drafts, fetcher = await self._drafts(
            {("GET", "/api/drafts/books/review"): (200, items, {"type": "array", "size": 1})}
        )

        result = await drafts.get_many("book", "review")

        self.assertEqual(result, {"items": items, "total": 1})
        self.assertEqual(fetcher.calls[0][1], "/api/drafts/books/review")

    async def test_save_puts_the_fields(self):
        drafts, fetcher = await self._drafts(
            {("PUT", "/api/drafts/books/dune/review"): (200, {"_id": "dune", "title": "revised"})}
        )

        document = await drafts.save("book", "dune", "review", {"title": "revised"})

        self.assertEqual(document["title"], "revised")
        method, _, _, body = fetcher.calls[0]
        self.assertEqual(method, "PUT")

    async def test_publish_posts_to_the_publish_route(self):
        drafts, fetcher = await self._drafts(
            {("POST", "/api/drafts/books/dune/review/publish"): (200, {"_id": "dune"})}
        )

        document = await drafts.publish("book", "dune", "review")

        self.assertEqual(document, {"_id": "dune"})
        self.assertEqual(fetcher.calls[0][1], "/api/drafts/books/dune/review/publish")

    async def test_discard_deletes_the_draft_route(self):
        drafts, fetcher = await self._drafts({("DELETE", "/api/drafts/books/dune/review"): (200, {})})

        result = await drafts.discard("book", "dune", "review")

        self.assertIsNone(result)
        self.assertEqual(fetcher.calls[0][0], "DELETE")


if __name__ == "__main__":
    unittest.main()
