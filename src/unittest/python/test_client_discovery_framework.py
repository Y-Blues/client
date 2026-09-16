"""
Real-framework integration test for discovery-gated proxy creation (design spec §10): proves, with
a genuine Pelix/iPOPO Framework, that

  (a) when "__remote_capabilities__" reports a strict subset of the four known interfaces
      (ICrud + IItemCatalog here), ONLY the matching Remote* get created - IDrafts/IServiceEndpoint
      are absent from the Pelix registry altogether, not merely unused;
  (b) when discovery itself is unavailable (no such service published at all), the existing
      unconditional four-interface behaviour (components.py, untouched) is the fallback - this is
      NOT a regression test for components.py itself (test_client_framework.py already covers
      that with "ycappuccino.client" in bundle_prefix directly); it proves the discovery PATH
      degrades to the exact same observable outcome when discovery fails.

Both scenarios run discovery.prepare_generated_module() BEFORE Framework().init() is ever called -
see discovery.py's own module docstring for why this sidesteps core/README.md's "Piège de timing"
entirely (nothing here ever calls instantiate_component() from a component's own start(), on a
background thread or otherwise: discovery happens as ordinary, synchronous-looking bootstrap code,
strictly before the framework exists, and its result becomes an ordinary Python source file that
bundle_prefix's normal, un-hacked scan then picks up like any hand-written module - never
"ycappuccino.client" itself, which would also pull in components.py's own unconditional four and
collide, see discovery.without_client_components()/module docstring).

Assertions poll the real Pelix service registry directly (context.get_service_reference(name))
rather than injecting into an application component with Optional[...] dependencies: a first
version of this test did the latter and was genuinely flaky - RemoteCrud REQUIRES (not optionally)
an IItemCatalog (spec §9.3's item_id -> plural resolution), so it can only validate once
RemoteItemCatalog already has; an application component with an Optional[ICrud] dependency and NO
required dependency of its own can validate (and capture its one-shot optional injection) BEFORE
that chain finishes, permanently observing None even though ICrud does become available moments
later. Polling the registry directly (wait_until, generous timeout - genuine AsyncRunner OS
threads are involved, see test_client_framework.py's own comment on this) is not subject to that
one-shot-optional-injection timing at all.
"""

import asyncio
import json
import os
import unittest

from fake_fetcher import FakeFetcher

from ycappuccino.core.framework import Framework
from ycappuccino.core.testing import TemporaryApplication, wait_until

from ycappuccino.client import discovery
from ycappuccino.client.transport import RawResponse

APPLICATION = {
    # Order matters (Framework.load_bundles() installs bundle_prefix entries package by package,
    # IN ORDER - core/README.md's own "Piège d'ordonnancement", already relied on elsewhere in
    # this repo, see design spec §9.2's IHttpFetcher investigation for the same guarantee cited by
    # name): "ycappuccino.client.transport" (HttpTransport) must come first because
    # PACKAGEgenerated's Remote* have a REQUIRED (not optional) `transport: HttpTransport`
    # constructor dependency (remote_proxy.py's _build_init) - discovered empirically while writing
    # this test (a first attempt listed it last and every Remote* simply never validated, no
    # exception, no service ever registered - iPOPO just kept waiting, forever, on a dependency
    # whose provider bundle had not even been installed yet).
    "conf/application.yml": """
        name: clientdiscoverytest
        bundle_prefix:
          - ycappuccino.client.transport
          - PACKAGEgenerated
        config:
          shell:
            console: false
    """,
}

BOOK = {
    "id": "book", "plural": "books", "app": "library", "module": "library.books",
    "secure_read": False, "secure_write": False, "writable": True, "multipart": False, "refs": [],
}


async def _fake_items_transport(method, url, headers, body):
    """the ONLY http_server route the running framework's HttpTransport needs in either scenario:
    RemoteItemCatalog is the one Remote* whose start() makes a real request (convention 4's bulk
    fetch, see remote_proxy.py) - RemoteCrud/RemoteDrafts/RemoteServiceEndpoint make none at
    start()."""
    path = url.split("?", 1)[0]
    if path == "/api/items":
        payload = {"status": 200, "meta": {"type": "array", "size": 1}, "data": [BOOK]}
    else:
        payload = {"status": 404, "meta": {"type": "object"}, "data": {"error": "not found"}}
    return RawResponse(status=payload["status"], headers={}, body=json.dumps(payload).encode())


def _patch_pyodide_transport(test_case):
    import ycappuccino.client.pyodide_transport as pyodide_transport_module

    original = pyodide_transport_module.pyodide_transport
    pyodide_transport_module.pyodide_transport = _fake_items_transport
    test_case.addClassCleanup(setattr, pyodide_transport_module, "pyodide_transport", original)


class TestDiscoveryGatedSubset(unittest.TestCase):
    """scenario (a): the backend reports only ICrud + IItemCatalog"""

    @classmethod
    def setUpClass(cls):
        _patch_pyodide_transport(cls)

        cls.app = TemporaryApplication(APPLICATION).open()
        cls.addClassCleanup(cls.app.close)

        capabilities_fetcher = FakeFetcher({
            ("POST", "/api/services/__remote_capabilities__"): (200, [
                {"module": "storage.manager", "class": "Manager",
                 "provides": ["ycappuccino.api.endpoints_storage.ICrud", "storage.manager.Manager"]},
                {"module": "storage.catalog", "class": "Catalog",
                 "provides": ["ycappuccino.api.endpoints_storage.IItemCatalog", "storage.catalog.Catalog"]},
            ]),
        })
        generated_path = os.path.join(cls.app.root, cls.app.package + "generated.py")
        asyncio.run(discovery.prepare_generated_module(generated_path, fetcher=capabilities_fetcher))

        cls.framework = Framework()
        cls.framework.init(cls.app.yml_path)
        cls.addClassCleanup(cls.framework.stop)
        # generous timeout: this genuinely starts an AsyncRunner OS thread (core/async_runner.py)
        # to validate every component; under a loaded machine, thread scheduling can be slow.
        found = wait_until(lambda: cls.framework.context.get_service_reference("HttpTransport"), timeout=15.0)
        assert found, "HttpTransport did not register as a service within 15s"

    def test_icrud_is_created(self):
        reference = wait_until(lambda: self.framework.context.get_service_reference("ICrud"), timeout=15.0)

        self.assertIsNotNone(reference)

    def test_iitemcatalog_is_created(self):
        reference = wait_until(lambda: self.framework.context.get_service_reference("IItemCatalog"), timeout=15.0)

        self.assertIsNotNone(reference)

    def test_idrafts_is_not_created_at_all(self):
        # deterministic, no race: RemoteDrafts's class was never even generated into
        # PACKAGEgenerated for this scenario, so no amount of waiting would ever produce it.
        self.assertIsNone(self.framework.context.get_service_reference("IDrafts"))

    def test_iserviceendpoint_is_not_created_at_all(self):
        self.assertIsNone(self.framework.context.get_service_reference("IServiceEndpoint"))


class TestDiscoveryUnavailableFallsBackToAllFour(unittest.TestCase):
    """scenario (b): "__remote_capabilities__" is not published at all - today's unconditional
    four-interface behaviour must still be the outcome, unregressed"""

    @classmethod
    def setUpClass(cls):
        _patch_pyodide_transport(cls)

        cls.app = TemporaryApplication(APPLICATION).open()
        cls.addClassCleanup(cls.app.close)

        no_capabilities_fetcher = FakeFetcher({})  # no route at all: discovery fails -> None
        generated_path = os.path.join(cls.app.root, cls.app.package + "generated.py")
        asyncio.run(discovery.prepare_generated_module(generated_path, fetcher=no_capabilities_fetcher))

        cls.framework = Framework()
        cls.framework.init(cls.app.yml_path)
        cls.addClassCleanup(cls.framework.stop)
        found = wait_until(lambda: cls.framework.context.get_service_reference("HttpTransport"), timeout=15.0)
        assert found, "HttpTransport did not register as a service within 15s"

    def test_all_four_are_created(self):
        for name in ("ICrud", "IDrafts", "IItemCatalog", "IServiceEndpoint"):
            reference = wait_until(lambda name=name: self.framework.context.get_service_reference(name), timeout=15.0)
            self.assertIsNotNone(reference, name)


if __name__ == "__main__":
    unittest.main()
