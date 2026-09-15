"""
Proves, in plain CPython (no Pyodide needed: the model code has no Pyodide-specific behaviour),
that a shared @Item model can be built from a JSON document fetched through RemoteCrud and read
back with its own get_storage_model(), exactly like ycappuccino.storage.manager.Manager.get_one
does server-side (create_item(item, document) then model.on_read(False), see
storage/src/main/python/ycappuccino/storage/manager.py).

example/ is added to sys.path here rather than declared as a package dependency: in the browser,
this is what micropip/pyscript's file-fetching does for an application's own model module - it
lands on sys.path, it is not "installed" as a wheel dependency of ycappuccino-client.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "example"))

from library.books import Book  # noqa: E402

from fake_catalog import FakeItemCatalog  # noqa: E402
from fake_fetcher import FakeFetcher  # noqa: E402
from ycappuccino.client.remote_crud import RemoteCrud  # noqa: E402
from ycappuccino.client.transport import HttpTransport  # noqa: E402

DUNE = {"_id": "dune", "title": "Dune", "pages": 412}


class TestSharedModelRoundTrip(unittest.TestCase):
    def test_a_plain_document_builds_a_book_and_reads_back_the_same_document(self):
        book = Book(dict(DUNE))
        book.on_read(False)

        self.assertEqual(book.get_storage_model(), DUNE)
        self.assertEqual(book._title, "Dune")
        self.assertEqual(book._pages, 412)


class TestSharedModelFromRemoteCrud(unittest.IsolatedAsyncioTestCase):
    async def test_a_document_fetched_through_remote_crud_builds_a_book(self):
        fetcher = FakeFetcher({("GET", "/api/crud/books/dune"): (200, dict(DUNE))})
        transport = HttpTransport(fetcher=fetcher)
        await transport.start()
        crud = RemoteCrud(transport, FakeItemCatalog({"book": "books"}))

        document = await crud.get_one("book", "dune")
        book = Book(document)
        book.on_read(False)

        self.assertEqual(book.get_storage_model(), DUNE)
        self.assertEqual(book._title, "Dune")


if __name__ == "__main__":
    unittest.main()
