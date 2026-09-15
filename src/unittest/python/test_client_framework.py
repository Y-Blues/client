"""
Real-framework integration test: starts a genuine ycappuccino.core.framework.Framework in
CPython, with bundle_prefix listing "ycappuccino.client" itself (not a hand-constructed
RemoteCrud/RemoteItemCatalog/RemoteServiceEndpoint) plus a small application package. The
application's own Demo component depends on ICrud/IItemCatalog/IServiceEndpoint - the plain api
interfaces, exactly as it would on a real backend - with ZERO reference to ycappuccino.client's
classes: this is the proof that "include ycappuccino.client in bundle_prefix" is enough to make
those interfaces resolve to RemoteCrud/RemoteItemCatalog/RemoteServiceEndpoint through real
Pelix/iPOPO DI, the same ergonomics as "include ycappuccino.storage" giving a working IManager for
free (core/README.md).

Only the bottom of the chain is faked: the application package also publishes a
ycappuccino.client.transport.IHttpFetcher component (FakeFetcher) so HttpTransport never attempts
a real pyodide.http.pyfetch call (this test runs in plain CPython, not Pyodide) - see
ycappuccino.client.transport's docstring for why this works reliably: PACKAGE is listed BEFORE
ycappuccino.client in bundle_prefix, so FakeFetcher is already a registered service before
HttpTransport (an Optional[IHttpFetcher] dependency) validates - Framework.load_bundles installs
and validates bundles package by package, in bundle_prefix order (the exact same ordering
guarantee hosts/scheduler's own framework tests rely on, see their READMEs/tests). Everything
above HttpTransport (RemoteCrud, RemoteDrafts, RemoteItemCatalog, RemoteServiceEndpoint, and the
Demo component's own DI) is 100% real: real Pelix bundles, real constructor injection, real
async_runner bridging - only the raw HTTP call is replaced by a Python object returning canned
bytes.
"""

import unittest

from ycappuccino.core.framework import Framework
from ycappuccino.core.testing import TemporaryApplication, wait_until

APPLICATION = {
    "conf/application.yml": """
        name: clienttest
        bundle_prefix:
          - PACKAGE
          - ycappuccino.client
        config:
          shell:
            console: false
    """,
    # PACKAGE (FakeFetcher, Demo) is scanned before ycappuccino.client: see this file's docstring
    # and ycappuccino.client.transport's docstring for why that ordering matters here (it does
    # not for Demo's own ICrud/IItemCatalog/IServiceEndpoint dependencies, which are mandatory and
    # so are resolved whenever they become available, regardless of scan order - only
    # HttpTransport's *optional* fetcher dependency is sensitive to it).
    "PACKAGE/__init__.py": "",
    "PACKAGE/fake_fetcher.py": """
        import json

        from ycappuccino.client.transport import IHttpFetcher, RawResponse

        BOOK = {
            "id": "book", "plural": "books", "app": "library", "module": "library.books",
            "secure_read": False, "secure_write": False, "writable": True, "multipart": False,
            "refs": [],
        }


        class FakeFetcher(IHttpFetcher):
            requests = []

            def __init__(self):
                pass

            async def start(self):
                pass

            async def stop(self):
                pass

            async def fetch(self, method, url, headers, body):
                FakeFetcher.requests.append((method, url))
                path = url.split("?", 1)[0]
                if path == "/api/items":
                    payload = {"status": 200, "meta": {"type": "array", "size": 1}, "data": [BOOK]}
                elif path == "/api/crud/books/dune":
                    payload = {
                        "status": 200, "meta": {"type": "object", "size": 1},
                        "data": {"_id": "dune", "title": "Dune"},
                    }
                elif path == "/api/services/echo":
                    payload = {
                        "status": 200, "meta": {"type": "object", "size": 1},
                        "data": {"echo": json.loads(body) if body else None},
                    }
                else:
                    payload = {"status": 404, "meta": {"type": "object"}, "data": {"error": "not found"}}
                return RawResponse(status=payload["status"], headers={}, body=json.dumps(payload).encode())
    """,
    "PACKAGE/demo.py": """
        from ycappuccino.api.core_base import YCappuccinoComponent
        from ycappuccino.api.endpoints_service import IServiceEndpoint
        from ycappuccino.api.endpoints_storage import ICrud, IItemCatalog


        class Demo(YCappuccinoComponent):
            items = None
            document = None
            echo_result = None

            def __init__(self, crud: ICrud, catalog: IItemCatalog, services: IServiceEndpoint):
                self._crud = crud
                self._catalog = catalog
                self._services = services

            async def start(self):
                Demo.items = await self._catalog.get_items()
                Demo.document = await self._crud.get_one("book", "dune")
                result = await self._services.call("echo", "POST", [], {}, {"hi": 1}, None)
                Demo.echo_result = result.body

            async def stop(self):
                pass
    """,
}


class TestClientInFramework(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = TemporaryApplication(APPLICATION).open()
        cls.addClassCleanup(cls.app.close)
        cls.framework = Framework()
        cls.framework.init(cls.app.yml_path)
        cls.addClassCleanup(cls.framework.stop)
        # generous timeout: this genuinely starts an AsyncRunner OS thread (core/async_runner.py)
        # to validate every component; under a loaded machine, thread scheduling can be slow.
        found = wait_until(lambda: cls.framework.context.get_service_reference("Demo"), timeout=15.0)
        assert found, "Demo component did not register as a service within 15s"

    def test_demo_receives_a_real_remote_item_catalog_through_plain_iitemcatalog(self):
        demo_module = self.app.module("demo")
        wait_until(lambda: demo_module.Demo.items is not None, timeout=15.0)

        self.assertEqual(demo_module.Demo.items[0]["id"], "book")

    def test_demo_receives_a_real_remote_crud_through_plain_icrud(self):
        demo_module = self.app.module("demo")
        wait_until(lambda: demo_module.Demo.document is not None, timeout=15.0)

        self.assertEqual(demo_module.Demo.document, {"_id": "dune", "title": "Dune"})

    def test_demo_receives_a_real_remote_service_endpoint_through_plain_iserviceendpoint(self):
        demo_module = self.app.module("demo")
        wait_until(lambda: demo_module.Demo.echo_result is not None, timeout=15.0)

        self.assertEqual(demo_module.Demo.echo_result, {"echo": {"hi": 1}})

    def test_every_call_went_through_the_fake_fetcher_not_a_real_network_call(self):
        fetcher_module = self.app.module("fake_fetcher")
        wait_until(lambda: len(fetcher_module.FakeFetcher.requests) >= 3, timeout=15.0)

        paths = [path for _, path in fetcher_module.FakeFetcher.requests]
        self.assertIn("/api/items", paths)
        self.assertIn("/api/crud/books/dune", paths)
        self.assertIn("/api/services/echo", paths)


if __name__ == "__main__":
    unittest.main()
