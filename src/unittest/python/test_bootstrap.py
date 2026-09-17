import unittest

import yaml

from ycappuccino.client.bootstrap import GENERATED_MODULE, application_yml


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


if __name__ == "__main__":
    unittest.main()
