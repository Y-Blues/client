"""
Every RemoteDrafts (ycappuccino.client.components) method against a fake IHttpFetcher. The
discard/save/publish trio is the trickiest case of the whole reflection design (spec §9.3): all
three end up on the SAME path as get_one, disambiguated only by HTTP verb, except publish, which
adds a "/publish" suffix - verified here against each of the four exactly.
"""

import unittest

from fake_catalog import FakeItemCatalog
from fake_fetcher import FakeFetcher

from ycappuccino.client.components import RemoteDrafts
from ycappuccino.client.transport import HttpTransport


class TestRemoteDrafts(unittest.IsolatedAsyncioTestCase):
    async def _drafts(self, routes):
        fetcher = FakeFetcher(routes)
        transport = HttpTransport(fetcher=fetcher)
        await transport.start()
        catalog = FakeItemCatalog({"book": "books"})
        return RemoteDrafts(transport, catalog), fetcher

    async def test_get_one_is_a_get_to_plural_slash_id_slash_draft(self):
        drafts, fetcher = await self._drafts(
            {("GET", "/api/drafts/books/dune/review"): (200, {"_id": "dune", "_draft": "review"})}
        )

        document = await drafts.get_one("book", "dune", "review")

        self.assertEqual(document["_draft"], "review")
        self.assertEqual(fetcher.calls[0][:2], ("GET", "/api/drafts/books/dune/review"))

    async def test_get_many_is_a_get_to_plural_slash_draft_no_id(self):
        items = [{"_id": "dune", "_draft": "review"}]
        drafts, fetcher = await self._drafts(
            {("GET", "/api/drafts/books/review"): (200, items, {"type": "array", "size": 1})}
        )

        result = await drafts.get_many("book", "review")

        self.assertEqual(result, {"items": items, "total": 1})
        self.assertEqual(fetcher.calls[0][:2], ("GET", "/api/drafts/books/review"))

    async def test_save_is_a_put_to_the_same_path_as_get_one_with_fields_as_body(self):
        drafts, fetcher = await self._drafts(
            {("PUT", "/api/drafts/books/dune/review"): (200, {"_id": "dune", "title": "revised"})}
        )

        document = await drafts.save("book", "dune", "review", {"title": "revised"})

        self.assertEqual(document["title"], "revised")
        method, url, _, _ = fetcher.calls[0]
        self.assertEqual(method, "PUT")
        self.assertEqual(url, "/api/drafts/books/dune/review")

    async def test_publish_is_a_post_with_a_publish_suffix(self):
        drafts, fetcher = await self._drafts(
            {("POST", "/api/drafts/books/dune/review/publish"): (200, {"_id": "dune"})}
        )

        document = await drafts.publish("book", "dune", "review")

        self.assertEqual(document, {"_id": "dune"})
        self.assertEqual(fetcher.calls[0][:2], ("POST", "/api/drafts/books/dune/review/publish"))

    async def test_discard_is_a_delete_to_the_same_path_as_get_one_no_suffix(self):
        """the trap this whole design has to avoid: discard must NOT get a "/discard" suffix -
        ApiServlet._route_drafts routes DELETE on the bare .../<id>/<draft> path to discard()"""
        drafts, fetcher = await self._drafts({("DELETE", "/api/drafts/books/dune/review"): (200, {})})

        result = await drafts.discard("book", "dune", "review")

        self.assertIsNone(result)
        method, url, _, _ = fetcher.calls[0]
        self.assertEqual(method, "DELETE")
        self.assertEqual(url, "/api/drafts/books/dune/review")  # NOT .../review/discard


if __name__ == "__main__":
    unittest.main()
