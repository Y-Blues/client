"""
Runs the README examples that make sense outside a browser: the Account component (interfaces and
ISession only, wired here by hand with proxies over a fake fetch), the generated module shape, and the
Book round trip. The browser bootstrap is not runnable here; the real wiring against a real backend is
test_client_framework.py.
"""

import asyncio
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "example"))

from library.books import Book  # noqa: E402

from fake_fetcher import FakeFetcher  # noqa: E402
from ycappuccino.api.core_base import YCappuccinoComponent  # noqa: E402
from ycappuccino.api.endpoints_storage import ICrud  # noqa: E402
from ycappuccino.api.permissions import ILoginService  # noqa: E402
from ycappuccino.client import discovery  # noqa: E402
from ycappuccino.client.rpc_proxy import make_rpc_proxy  # noqa: E402
from ycappuccino.client.transport import HttpTransport, ISession  # noqa: E402

DISPATCH = "/api/services/__remote_dispatch__/"
LOGIN = "ycappuccino.api.permissions.ILoginService"
CRUD = "ycappuccino.api.endpoints_storage.ICrud"


class Account(YCappuccinoComponent):

    def __init__(self, login: ILoginService, crud: ICrud, session: ISession):
        self._login = login
        self._crud = crud
        self._session = session

    async def start(self):
        pass

    async def stop(self):
        pass

    async def sign_in(self, login: str, password: str) -> None:
        self._session.set_token(await self._login.login(login, password))

    async def organization(self, id: str) -> dict:
        return await self._crud.get_one("organization", id)


class TestAccountExample(unittest.IsolatedAsyncioTestCase):

    async def test_signs_in_then_reads_with_the_token(self):
        fetcher = FakeFetcher({
            ("POST", DISPATCH + LOGIN + "/login"): (200, {"result": "eyJ"}),
            ("POST", DISPATCH + CRUD + "/get_one"): (200, {"result": {"_id": "acme"}}),
        })
        transport = HttpTransport(fetcher=fetcher)
        account = Account(make_rpc_proxy(ILoginService, LOGIN)(transport), make_rpc_proxy(ICrud, CRUD)(transport), transport)

        await account.sign_in("superadmin", "demo")
        organization = await account.organization("acme")

        self.assertEqual(organization, {"_id": "acme"})
        self.assertEqual(fetcher.calls[1][2]["Authorization"], "Bearer eyJ")


class TestGeneratedModuleExample(unittest.TestCase):

    def test_the_generated_module_declares_one_proxy_per_interface(self):
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory, True)
        fetcher = FakeFetcher({("GET", "/api/services/__remote_capabilities__"): (
            200, {"services": [], "components": [{"module": "m", "class": "C", "provides": [CRUD, LOGIN]}]},
        )})

        paths = asyncio.run(discovery.prepare_generated_module(os.path.join(directory, "generated_remote.py"), fetcher=fetcher))

        self.assertEqual(paths, [CRUD, LOGIN])
        with open(os.path.join(directory, "generated_remote.py")) as file:
            source = file.read()
        self.assertIn(f"RemoteCrud = make_rpc_proxy(ICrud, '{CRUD}')", source)
        self.assertIn(f"RemoteLoginService = make_rpc_proxy(ILoginService, '{LOGIN}')", source)


class TestSharedModelExample(unittest.TestCase):

    def test_the_book_round_trip_runs(self):
        book = Book({"_id": "dune", "title": "Dune", "pages": 412})
        book.on_read(False)

        self.assertEqual(book.get_storage_model(), {"_id": "dune", "title": "Dune", "pages": 412})


if __name__ == "__main__":
    unittest.main()
