import os
import sys
import tempfile
import unittest

from fake_fetcher import FakeFetcher

from ycappuccino.api.endpoints_service import IServiceEndpoint
from ycappuccino.api.endpoints_storage import ICrud, IDrafts, IItemCatalog
from ycappuccino.api.permissions import ILoginService
from ycappuccino.client import discovery

CAPABILITIES = "/api/services/__remote_capabilities__"
CRUD = "ycappuccino.api.endpoints_storage.ICrud"
LOGIN = "ycappuccino.api.permissions.ILoginService"
MANAGER = "ycappuccino.api.storage.IManager"


def _capabilities(*provides):
    return {"services": ["login"], "components": [{"module": "m", "class": "C", "provides": list(provides)}]}


def _discover(routes, **kwargs):
    import asyncio

    return asyncio.run(discovery.discover_backend_provides(fetcher=FakeFetcher(routes), **kwargs))


class TestDiscoverBackendProvides(unittest.TestCase):

    def test_collects_the_qualified_paths_of_every_component(self):
        routes = {("GET", CAPABILITIES): (200, _capabilities(CRUD, LOGIN))}

        self.assertEqual(_discover(routes), {CRUD, LOGIN})

    def test_no_component_reported_is_an_empty_set(self):
        self.assertEqual(_discover({("GET", CAPABILITIES): (200, {"services": []})}), set())

    def test_none_when_the_backend_has_no_capabilities_service(self):
        self.assertIsNone(_discover({("GET", CAPABILITIES): (404, {"error": "unknown service"})}))

    def test_none_on_a_malformed_response(self):
        self.assertIsNone(_discover({("GET", CAPABILITIES): (200, {"components": "nope"})}))

    def test_honors_an_explicit_base_url(self):
        routes = {("GET", "http://backend:8080/api/services/__remote_capabilities__"): (200, _capabilities(CRUD))}

        self.assertEqual(_discover(routes, base_url="http://backend:8080/api"), {CRUD})


class TestEnabledInterfaces(unittest.TestCase):

    def test_unknown_capabilities_fall_back_to_the_storage_and_service_use_cases(self):
        self.assertEqual(
            [interface for interface, _ in discovery.enabled_interfaces(None)],
            [ICrud, IDrafts, IItemCatalog, IServiceEndpoint],
        )

    def test_only_resolvable_public_interfaces_are_kept(self):
        enabled = discovery.enabled_interfaces({LOGIN, CRUD, MANAGER, "nowhere.INothing"})

        self.assertEqual(enabled, [(ICrud, CRUD), (ILoginService, LOGIN)])


class TestGeneratedModule(unittest.TestCase):

    def test_generates_an_importable_module_of_proxies(self):
        directory = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, directory, True)
        path = os.path.join(directory, "generated_remote_test.py")

        discovery.write_generated_module([(ICrud, CRUD), (ILoginService, LOGIN)], path)
        sys.path.insert(0, directory)
        self.addCleanup(sys.path.remove, directory)
        self.addCleanup(sys.modules.pop, "generated_remote_test", None)
        module = __import__("generated_remote_test")

        self.assertTrue(issubclass(module.RemoteCrud, ICrud))
        self.assertTrue(issubclass(module.RemoteLoginService, ILoginService))
        self.assertEqual(module.RemoteLoginService._ycappuccino_qualified_path, LOGIN)

    def test_two_interfaces_with_the_same_name_get_distinct_proxies(self):
        source = discovery.generated_module_source([(ICrud, CRUD), (ICrud, "other.module.ICrud")])

        self.assertIn("RemoteCrud = ", source)
        self.assertIn("RemoteCrud2 = ", source)


class TestWithoutClientComponents(unittest.TestCase):

    def test_swaps_the_whole_package_for_just_the_transport(self):
        self.assertEqual(
            discovery.without_client_components(["ycappuccino.client", "app"]),
            ["ycappuccino.client.transport", "app"],
        )


class TestPrepareGeneratedModule(unittest.TestCase):

    def test_writes_the_discovered_interfaces_and_returns_their_paths(self):
        import asyncio

        path = os.path.join(tempfile.mkdtemp(), "generated.py")
        self.addCleanup(__import__("shutil").rmtree, os.path.dirname(path), True)
        fetcher = FakeFetcher({("GET", CAPABILITIES): (200, _capabilities(LOGIN, MANAGER))})

        paths = asyncio.run(discovery.prepare_generated_module(path, fetcher=fetcher))

        self.assertEqual(paths, [LOGIN])
        with open(path) as file:
            self.assertIn("make_rpc_proxy(ILoginService", file.read())


if __name__ == "__main__":
    unittest.main()
