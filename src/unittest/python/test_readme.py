"""
Runs, in plain CPython, the parts of README.md's examples that are actually runnable outside a
browser: constructing an ApiClient with a fake transport, and the Book round-trip. The "Transport"
example and everything under static/ (pyscript, pyodide.http.pyfetch) are browser-only and are NOT
exercised here - they cannot be, without a real Pyodide runtime; see README.md "Limites et
verifications manuelles requises" and "Developper client".
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "example"))

from library.books import Book  # noqa: E402

from fake_transport import FakeTransport  # noqa: E402
from ycappuccino.client.http import ApiClient, RawResponse  # noqa: E402


class TestReadmeApiClientExample(unittest.IsolatedAsyncioTestCase):
    """mirrors README.md's "Exemple" section: get_one/get_many/create/update/delete/delete_many/call"""

    async def asyncSetUp(self):
        self.transport = FakeTransport(
            {
                ("GET", "http://localhost:9000/api/crud/books/dune"): (200, {"_id": "dune", "title": "Dune"}),
                ("GET", "http://localhost:9000/api/crud/books"): (
                    200,
                    [{"_id": "dune"}],
                    {"type": "array", "size": 1},
                ),
                ("POST", "http://localhost:9000/api/crud/books"): (
                    201,
                    {"_id": "dune", "title": "Dune", "pages": 412},
                ),
                ("PUT", "http://localhost:9000/api/crud/books/dune"): (200, {"_id": "dune", "pages": 412}),
                ("DELETE", "http://localhost:9000/api/crud/books/dune"): (200, {}),
                ("DELETE", "http://localhost:9000/api/crud/books"): (200, {"deleted": 1}),
                ("POST", "http://localhost:9000/api/services/echo"): (200, {"hello": "world"}),
            }
        )
        self.client = ApiClient("http://localhost:9000", token="demo", transport=self.transport)

    async def test_the_full_example_runs(self):
        document = await self.client.get_one("books", "dune")
        self.assertEqual(document["_id"], "dune")

        await self.client.get_many("books", {"filter": {"pages": {"$gte": 400}}, "sort": {"title": 1}})
        await self.client.create("books", {"title": "Dune", "pages": 412})
        await self.client.update("books", "dune", {"pages": 412})
        await self.client.delete("books", "dune")
        deleted = await self.client.delete_many("books", {"pages": {"$lt": 100}})
        self.assertEqual(deleted, 1)

        result = await self.client.call("echo", "POST", body={"hello": "world"})
        self.assertEqual(result, {"hello": "world"})

    async def test_the_shared_model_round_trip_example_runs(self):
        document = await self.client.get_one("books", "dune")
        book = Book(document)
        book.on_read(False)

        self.assertEqual(book.get_storage_model()["_id"], "dune")
        self.assertEqual(book.get_storage_model()["title"], "Dune")


class TestReadmeFakeTransportExample(unittest.IsolatedAsyncioTestCase):
    """mirrors README.md's "Transport" section, the CPython-runnable half of it (RawResponse shape)"""

    async def test_a_hand_written_fake_transport_matches_raw_response(self):
        async def fake_transport(method, url, headers, body):
            body = b'{"status":200,"meta":{"type":"object","size":1},"data":{"_id":"dune"}}'
            return RawResponse(status=200, headers={}, body=body)

        client = ApiClient("http://api", transport=fake_transport)
        document = await client.get_one("books", "dune")

        self.assertEqual(document, {"_id": "dune"})


if __name__ == "__main__":
    unittest.main()
