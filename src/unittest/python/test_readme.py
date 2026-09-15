"""
Runs, in plain CPython, the parts of README.md's examples that are actually runnable outside a
browser: the app-code-only Catalog component (ICrud/IItemCatalog, never ycappuccino.client
directly), the Login example (HttpTransport.set_token from a service call's response body), and
the Book round-trip. Everything under "Bootstrap navigateur" (static/index.html, static/main.py,
pyodide.loadPackage, micropip) is browser-only and NOT exercised here - it cannot be, without a
real Pyodide runtime; see README.md "Limites et verifications manuelles requises".
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "example"))

from library.books import Book  # noqa: E402
from library.catalog import Catalog  # noqa: E402

from fake_catalog import FakeItemCatalog  # noqa: E402
from fake_fetcher import FakeFetcher  # noqa: E402
from ycappuccino.client.remote_crud import RemoteCrud  # noqa: E402
from ycappuccino.client.remote_item_catalog import RemoteItemCatalog  # noqa: E402
from ycappuccino.client.remote_service_endpoint import RemoteServiceEndpoint  # noqa: E402
from ycappuccino.client.transport import HttpTransport  # noqa: E402

BOOK_ITEM = {
    "id": "book", "plural": "books", "app": "library", "module": "library.books",
    "secure_read": False, "secure_write": False, "writable": True, "multipart": False, "refs": [],
}


class Login:
    """mirrors README.md's "Session / authentification" example (Login component)"""

    def __init__(self, services, transport):
        self._services = services
        self._transport = transport

    async def log_in(self, login, password):
        result = await self._services.call(
            "login", "POST", [], {}, {"login": login, "password": password}, None
        )
        self._transport.set_token(result.body["token"])


class TestReadmeCatalogExample(unittest.IsolatedAsyncioTestCase):
    """mirrors README.md's "Ce que le code applicatif ecrit" + "Modele partage" sections"""

    async def test_catalog_depends_only_on_the_plain_interfaces_and_gets_wired_by_hand_here(self):
        fetcher = FakeFetcher(
            {
                ("GET", "/api/items"): (200, [BOOK_ITEM], {"type": "array", "size": 1}),
                ("GET", "/api/crud/books/dune"): (200, {"_id": "dune", "title": "Dune", "pages": 412}),
            }
        )
        transport = HttpTransport(fetcher=fetcher)
        await transport.start()
        item_catalog = RemoteItemCatalog(transport)
        await item_catalog.start()
        crud = RemoteCrud(transport, item_catalog)

        catalog = Catalog(crud, item_catalog)
        await catalog.start()

        self.assertEqual(catalog.items, [BOOK_ITEM])

        document = await crud.get_one("book", "dune")
        book = Book(document)
        book.on_read(False)
        self.assertEqual(book.get_storage_model()["title"], "Dune")


class TestReadmeLoginExample(unittest.IsolatedAsyncioTestCase):
    """mirrors README.md's "Session / authentification" login flow"""

    async def test_log_in_sets_the_token_from_the_service_result_body(self):
        fetcher = FakeFetcher({("POST", "/api/services/login"): (200, {"token": "eyJ..."})})
        transport = HttpTransport(fetcher=fetcher)
        await transport.start()
        services = RemoteServiceEndpoint(transport)
        login = Login(services, transport)

        await login.log_in("alice", "secret")

        self.assertEqual(transport.get_token(), "eyJ...")


class TestReadmeSharedModelRoundTrip(unittest.TestCase):
    def test_the_book_round_trip_runs(self):
        document = {"_id": "dune", "title": "Dune", "pages": 412}
        book = Book(document)
        book.on_read(False)

        self.assertEqual(book.get_storage_model(), document)


if __name__ == "__main__":
    unittest.main()
