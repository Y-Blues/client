"""
Real-framework integration test: starts a genuine ycappuccino.core.framework.Framework in
CPython, with bundle_prefix listing "ycappuccino.client" itself (not a hand-constructed
RemoteCrud/RemoteItemCatalog/RemoteServiceEndpoint) plus a small application package. The
application's own Demo component depends on ICrud/IItemCatalog/IServiceEndpoint - the plain api
interfaces, exactly as it would on a real backend - with ZERO reference to ycappuccino.client's
classes (not even the fact that Remote* are synthesized by reflection, see remote_proxy.py):
this is the proof that "include ycappuccino.client in bundle_prefix" is enough to make those
interfaces resolve to RemoteCrud/RemoteItemCatalog/RemoteServiceEndpoint (ycappuccino.client
.components) through real Pelix/iPOPO DI, with a REAL, introspectable, exec-forged __init__
(see remote_proxy.py's _build_init and design spec §9.2) - the same ergonomics as "include
ycappuccino.storage" giving a working IManager for free (core/README.md).

FAKING THE TRANSPORT - A REAL BUG DISCOVERED WHILE WRITING THIS TEST, NOT A HYPOTHETICAL:
the first version of this test published a fake ycappuccino.client.transport.IHttpFetcher
component from PACKAGE (listed before ycappuccino.client in bundle_prefix, exactly like the
Optional[IHttpFetcher] mechanism ycappuccino.client.transport.HttpTransport was designed
around). It failed DETERMINISTICALLY (confirmed via direct instrumentation of
HttpTransport.__init__: fetcher=None every single time), even though the fake fetcher's service
was independently confirmed present and discoverable in the registry at that exact moment
(framework.context.get_service_reference("IHttpFetcher") found it). Isolated by elimination
(minimal repros with a hand-written Optional[IThing] consumer/provider pair): the bug reproduces
ONLY when the consumer (HttpTransport) lives in the "ycappuccino.*" namespace package while the
provider lives in a temporary test package - the EXACT SAME quirk hosts/servlet.py's own
docstring already documents ("an optional dependency satisfied elsewhere in the same multi-path
'ycappuccino.*' namespace package was observed to resolve non-deterministically (sometimes None)
depending on scan timing"). hosts' own fix was to make the dependency mandatory instead; that is
not an option here (HttpTransport's fetcher must default to none in real deployments). Fix used
here instead: bypass Pelix DI entirely for the fake transport - monkeypatch the plain module-level
function HttpTransport falls back to (ycappuccino.client.pyodide_transport.pyodide_transport) with
plain Python attribute assignment, BEFORE starting the framework. HttpTransport.request() does
`from ycappuccino.client.pyodide_transport import pyodide_transport` freshly on every call (never
importing it at module level, see that module's docstring), so it picks up whatever function
object is bound to that name at CALL time - a plain, single-threaded, GIL-protected attribute
read/write, with none of Pelix's cross-namespace-package service-registry timing involved. This
also means ycappuccino.client.transport.IHttpFetcher (kept in the code as a documented, but now
KNOWN-FRAGILE-ACROSS-NAMESPACE-PACKAGES, extension point - see its docstring and design spec §9.4)
is NOT exercised by this test; it IS exercised by test_transport.py, entirely in-process, with no
Pelix involved at all, where this quirk cannot occur.
"""

import json
import unittest

from ycappuccino.core.framework import Framework
from ycappuccino.core.testing import TemporaryApplication, wait_until

# plain CPython import: ycappuccino.client.transport never imports pelix/pyodide at module level.
from ycappuccino.client.transport import RawResponse

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
    "PACKAGE/__init__.py": "",
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

BOOK = {
    "id": "book", "plural": "books", "app": "library", "module": "library.books",
    "secure_read": False, "secure_write": False, "writable": True, "multipart": False, "refs": [],
}


class FakeRequestLog:
    """records every (method, path) HttpTransport's fallback fetch is asked to perform"""

    calls: list = []


async def _fake_pyodide_transport(method, url, headers, body):
    FakeRequestLog.calls.append((method, url))
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


class TestClientInFramework(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        import ycappuccino.client.pyodide_transport as pyodide_transport_module

        cls._original_pyodide_transport = pyodide_transport_module.pyodide_transport
        pyodide_transport_module.pyodide_transport = _fake_pyodide_transport
        cls.addClassCleanup(setattr, pyodide_transport_module, "pyodide_transport", cls._original_pyodide_transport)

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

    def test_every_call_went_through_the_fake_transport_not_a_real_network_call(self):
        wait_until(lambda: len(FakeRequestLog.calls) >= 3, timeout=15.0)

        paths = [path for _, path in FakeRequestLog.calls]
        self.assertIn("/api/items", paths)
        self.assertIn("/api/crud/books/dune", paths)
        self.assertIn("/api/services/echo", paths)


if __name__ == "__main__":
    unittest.main()
