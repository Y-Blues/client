import unittest

import yaml

from ycappuccino.client.bootstrap import GENERATED_MODULE, api_base_url, application_yml


class TestApplicationYml(unittest.TestCase):

    def test_the_transport_and_the_generated_proxies_are_scanned_before_the_application(self):
        document = yaml.safe_load(
            application_yml("admin", ["ycappuccino.ui_web.page", "myapp"], {"PyodidePage": {"mount_selector": "#main"}})
        )

        self.assertEqual(
            document,
            {
                "name": "admin",
                "bundle_prefix": ["ycappuccino.client.transport", GENERATED_MODULE, "ycappuccino.ui_web.page", "myapp"],
                "components": {"PyodidePage": {"mount_selector": "#main"}},
                "config": {"shell": {"console": False}},
            },
        )

    def test_without_components_there_is_no_components_section(self):
        self.assertNotIn("components", yaml.safe_load(application_yml("admin", ["myapp"])))



class TestApiBaseUrl(unittest.TestCase):
    """discovery asks the same API the proxies will call"""

    def test_the_configured_client_base_url_is_used(self):
        self.assertEqual(api_base_url(None, {"client.base_url": "http://localhost:8303/api"}), "http://localhost:8303/api")

    def test_an_explicit_base_url_wins(self):
        self.assertEqual(api_base_url("http://a/api", {"client.base_url": "http://b/api"}), "http://a/api")

    def test_without_either_the_page_origin_is_used(self):
        self.assertIsNone(api_base_url(None, None))


if __name__ == "__main__":
    unittest.main()
