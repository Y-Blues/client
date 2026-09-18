"""
start_client: starts a client YCappuccino Framework -- in a browser under Pyodide, or in CPython for a
test -- the same way every time:

1. discovery: ask the backend which public interfaces it provides and write one JSON-RPC proxy per
   interface into <root>/generated_remote.py (ycappuccino.client.discovery);
2. write <root>/conf/application.yml scanning ycappuccino.client.transport (HttpTransport, the ISession),
   then the generated proxies, then the application's bundles, and <root>/conf/config.properties;
3. make <root> the working directory and importable, and init the Framework.

The proxies exist before the application's components are validated, so those may require backend
interfaces like any local dependency.
"""

import os
import sys
from typing import Any

import yaml

from ycappuccino.client import discovery
from ycappuccino.client.transport import CLIENT_BASE_URL, IHttpFetcher
from ycappuccino.core.framework import Framework

GENERATED_MODULE = "generated_remote"


def application_yml(name: str, bundles: list[str], components: dict[str, dict] | None = None) -> str:
    document: dict[str, Any] = {
        "name": name,
        "bundle_prefix": ["ycappuccino.client.transport", GENERATED_MODULE, *bundles],
    }
    if components:
        document["components"] = components
    document["config"] = {"shell": {"console": False}}
    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True)


def api_base_url(base_url: str | None, properties: dict[str, str] | None) -> str | None:
    """the backend API discovery asks: the explicit one, else the configured client.base_url (the one the
    proxies call), else None -- the page's own origin"""
    if base_url is not None:
        return base_url
    return (properties or {}).get(CLIENT_BASE_URL)


async def start_client(
    name: str,
    bundles: list[str],
    components: dict[str, dict] | None = None,
    properties: dict[str, str] | None = None,
    root: str = ".",
    fetcher: IHttpFetcher | None = None,
    base_url: str | None = None,
) -> tuple[Framework, list[str]]:
    """the started Framework and the qualified paths of the backend interfaces proxied"""
    root = os.path.abspath(root)
    os.makedirs(os.path.join(root, "conf"), exist_ok=True)
    proxied = await discovery.prepare_generated_module(
        os.path.join(root, f"{GENERATED_MODULE}.py"), fetcher=fetcher, base_url=api_base_url(base_url, properties)
    )
    yml_path = os.path.join(root, "conf", "application.yml")
    with open(yml_path, "w") as file:
        file.write(application_yml(name, bundles, components))
    with open(os.path.join(root, "conf", "config.properties"), "w") as file:
        file.writelines(f"{key}={value}\n" for key, value in (properties or {}).items())

    os.chdir(root)
    if root not in sys.path:
        sys.path.insert(0, root)
    framework = Framework()
    framework.init(yml_path)
    return framework, proxied
