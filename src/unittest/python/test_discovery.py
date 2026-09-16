"""
ycappuccino.client.discovery, component-level (no framework at all, see core/README.md "Tester
ses composants") - the pieces test_client_discovery_framework.py's real-framework test composes:
discover_backend_provides()'s call to "__remote_capabilities__" through the existing generic
"/api/services/<name>" route, its graceful degradation to None on ANY failure,
enabled_known_interfaces()'s filtering (discovered vs. fallback-to-all-four),
generated_module_source()'s exact generated code, and without_client_components()'s bundle_prefix
surgery.
"""

import asyncio
import unittest

from fake_fetcher import FakeFetcher

from ycappuccino.api.endpoints_service import IServiceEndpoint
from ycappuccino.api.endpoints_storage import ICrud, IDrafts, IItemCatalog
from ycappuccino.client import discovery
from ycappuccino.client.known_interfaces import KNOWN_INTERFACES


def _run(coroutine):
    return asyncio.run(coroutine)


class TestDiscoverBackendProvides(unittest.TestCase):

    def test_flattens_provides_from_every_reported_component(self):
        fetcher = FakeFetcher({
            ("POST", "/api/services/__remote_capabilities__"): (200, [
                {"module": "storage.manager", "class": "Manager",
                 "provides": ["ycappuccino.api.endpoints_storage.ICrud", "storage.manager.Manager"]},
                {"module": "storage.catalog", "class": "Catalog",
                 "provides": ["ycappuccino.api.endpoints_storage.IItemCatalog", "storage.catalog.Catalog"]},
            ]),
        })

        provides = _run(discovery.discover_backend_provides(fetcher=fetcher))

        self.assertEqual(
            provides,
            {
                "ycappuccino.api.endpoints_storage.ICrud", "storage.manager.Manager",
                "ycappuccino.api.endpoints_storage.IItemCatalog", "storage.catalog.Catalog",
            },
        )

    def test_calls_through_the_existing_generic_named_service_route_with_zero_special_casing(self):
        fetcher = FakeFetcher({("POST", "/api/services/__remote_capabilities__"): (200, [])})

        _run(discovery.discover_backend_provides(fetcher=fetcher))

        self.assertEqual(fetcher.calls[0][0], "POST")
        self.assertEqual(fetcher.calls[0][1].split("?", 1)[0], "/api/services/__remote_capabilities__")

    def test_none_when_the_backend_does_not_expose_the_capabilities_service(self):
        fetcher = FakeFetcher({})  # no route at all -> AssertionError inside FakeFetcher.fetch

        provides = _run(discovery.discover_backend_provides(fetcher=fetcher))

        self.assertIsNone(provides)

    def test_none_on_a_404_not_found(self):
        fetcher = FakeFetcher({
            ("POST", "/api/services/__remote_capabilities__"): (404, {"error": "not found"}),
        })

        provides = _run(discovery.discover_backend_provides(fetcher=fetcher))

        self.assertIsNone(provides)

    def test_none_on_a_malformed_response_shape(self):
        fetcher = FakeFetcher({
            ("POST", "/api/services/__remote_capabilities__"): (200, {"not": "a list of dicts"}),
        })

        provides = _run(discovery.discover_backend_provides(fetcher=fetcher))

        self.assertIsNone(provides)

    def test_honors_an_explicit_base_url_since_no_iconfiguration_exists_yet_before_init(self):
        fetcher = FakeFetcher({("POST", "/other/services/__remote_capabilities__"): (200, [])})

        provides = _run(discovery.discover_backend_provides(fetcher=fetcher, base_url="/other"))

        self.assertEqual(provides, set())


class TestEnabledKnownInterfaces(unittest.TestCase):

    def test_none_falls_back_to_every_known_interface_unchanged(self):
        self.assertEqual(discovery.enabled_known_interfaces(None), list(KNOWN_INTERFACES))

    def test_only_the_discovered_known_interfaces_are_enabled(self):
        discovered = {"ycappuccino.api.endpoints_storage.ICrud", "ycappuccino.api.endpoints_storage.IItemCatalog"}

        enabled = discovery.enabled_known_interfaces(discovered)

        self.assertEqual([interface for interface, _, _ in enabled], [ICrud, IItemCatalog])

    def test_empty_set_enables_nothing(self):
        self.assertEqual(discovery.enabled_known_interfaces(set()), [])

    def test_an_unresolvable_or_unknown_path_is_silently_dropped(self):
        discovered = {
            "ycappuccino.api.endpoints_storage.ICrud",
            "not.a.real.module.Thing",
            "ycappuccino.client.discovery.CAPABILITIES_SERVICE_NAME",  # resolves, but not an interface: a str constant, not a class
        }

        enabled = discovery.enabled_known_interfaces(discovered)

        self.assertEqual([interface for interface, _, _ in enabled], [ICrud])


class TestGeneratedModuleSource(unittest.TestCase):

    def test_generates_a_working_module_for_a_subset(self):
        enabled = [spec for spec in KNOWN_INTERFACES if spec[0] in (ICrud, IItemCatalog)]

        source = discovery.generated_module_source(enabled)
        namespace: dict = {}
        exec(compile(source, "<generated>", "exec"), namespace)

        self.assertIn("RemoteCrud", namespace)
        self.assertIn("RemoteItemCatalog", namespace)
        self.assertNotIn("RemoteDrafts", namespace)
        self.assertNotIn("RemoteServiceEndpoint", namespace)
        self.assertTrue(issubclass(namespace["RemoteCrud"], ICrud))

    def test_empty_selection_generates_a_module_with_no_remote_classes_at_all(self):
        source = discovery.generated_module_source([])
        namespace: dict = {}
        exec(compile(source, "<generated>", "exec"), namespace)

        self.assertNotIn("RemoteCrud", namespace)
        self.assertNotIn("RemoteDrafts", namespace)
        self.assertNotIn("RemoteItemCatalog", namespace)
        self.assertNotIn("RemoteServiceEndpoint", namespace)

    def test_write_generated_module_creates_an_importable_file(self):
        import importlib
        import sys
        import tempfile
        import os

        with tempfile.TemporaryDirectory() as directory:
            file_path = os.path.join(directory, "generated_remote.py")
            discovery.write_generated_module(
                [spec for spec in KNOWN_INTERFACES if spec[0] is IServiceEndpoint], file_path
            )

            sys.path.insert(0, directory)
            try:
                module = importlib.import_module("generated_remote")
                self.assertTrue(hasattr(module, "RemoteServiceEndpoint"))
                self.assertFalse(hasattr(module, "RemoteCrud"))
            finally:
                sys.path.remove(directory)
                sys.modules.pop("generated_remote", None)


class TestWithoutClientComponents(unittest.TestCase):

    def test_swaps_the_whole_package_for_just_transport(self):
        result = discovery.without_client_components(["PACKAGE", "ycappuccino.client"])

        self.assertEqual(result, ["PACKAGE", "ycappuccino.client.transport"])

    def test_leaves_other_entries_untouched(self):
        result = discovery.without_client_components(["PACKAGE", "other.thing"])

        self.assertEqual(result, ["PACKAGE", "other.thing"])


class TestPrepareGeneratedModule(unittest.TestCase):

    def test_end_to_end_writes_the_discovered_subset(self):
        import tempfile
        import os

        fetcher = FakeFetcher({
            ("POST", "/api/services/__remote_capabilities__"): (200, [
                {"module": "m", "class": "C", "provides": ["ycappuccino.api.endpoints_storage.IItemCatalog"]},
            ]),
        })

        with tempfile.TemporaryDirectory() as directory:
            file_path = os.path.join(directory, "generated_remote.py")

            resources = _run(discovery.prepare_generated_module(file_path, fetcher=fetcher))

            self.assertEqual(resources, ["items"])
            with open(file_path) as file:
                content = file.read()
            self.assertIn("RemoteItemCatalog", content)
            self.assertNotIn("RemoteCrud", content)

    def test_end_to_end_falls_back_to_all_four_when_discovery_fails(self):
        import tempfile
        import os

        fetcher = FakeFetcher({})  # no capabilities route: discovery fails

        with tempfile.TemporaryDirectory() as directory:
            file_path = os.path.join(directory, "generated_remote.py")

            resources = _run(discovery.prepare_generated_module(file_path, fetcher=fetcher))

            self.assertEqual(sorted(resources), ["crud", "drafts", "items", "services"])


if __name__ == "__main__":
    unittest.main()
