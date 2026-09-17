"""
End to end, over real HTTP: a real backend (storage, endpoints_storage, endpoints_service, http_server,
permissions_app, and ycappuccino.remote's dispatch/capabilities modules) runs in a subprocess; this
process runs the client exactly as the browser bootstrap does, only in CPython:

1. bootstrap.start_client: discovery asks the backend which public interfaces it provides and writes the
   proxy module, then a real Framework starts with ycappuccino.client.transport, that generated module and
   an application package whose Demo component depends on ILoginService, ICrud and ISession only,
2. Demo signs in and calls secured use cases through generated JSON-RPC proxies.

The only substitution: ycappuccino.client.pyodide_transport.pyodide_transport, which needs Pyodide, is
replaced by an equivalent urllib fetch. Nothing else is faked.
"""

import asyncio
import json
import subprocess
import sys
import unittest
import urllib.error
import urllib.request

from ycappuccino.api.endpoints_service import ServiceResult
from ycappuccino.api.endpoints_storage import InvalidRequest, NotAuthenticated, NotFound
from ycappuccino.client import bootstrap
from ycappuccino.client.transport import RawResponse
from ycappuccino.core.testing import TemporaryApplication, wait_until

BACKEND_PORT = 18170
BASE_URL = f"http://localhost:{BACKEND_PORT}/api"
KEY = "client-test-key"

BACKEND_APPLICATION = {
    "conf/application.yml": f"""
        name: clientbackend
        bundle_prefix:
          - ycappuccino.storage
          - ycappuccino.endpoints_storage
          - ycappuccino.endpoints_service
          - ycappuccino.http_server
          - ycappuccino.permissions
          - ycappuccino.remote.dispatch
          - ycappuccino.remote.capabilities
        layers:
          ycappuccino_storage_memory:
            active: true
        components:
          JwtAuthentication:
            key: {KEY}
          PasswordLogin:
            key: {KEY}
          FrontendShell:
            key: {KEY}
        config:
          http_server:
            active: true
            port: {BACKEND_PORT}
            ip: localhost
          shell:
            console: false
    """,
    "conf/config.properties": "permissions.superadmin.password=demo\n",
}

CLIENT_APPLICATION = {
    "PACKAGE/__init__.py": "",
    "PACKAGE/demo.py": """
        from ycappuccino.api.core_base import YCappuccinoComponent
        from ycappuccino.api.endpoints_storage import ICrud
        from ycappuccino.api.permissions import ILoginService
        from ycappuccino.client.transport import ISession


        class Demo(YCappuccinoComponent):

            def __init__(self, login: ILoginService, crud: ICrud, session: ISession):
                self._login = login
                self._crud = crud
                self._session = session

            async def start(self):
                pass

            async def stop(self):
                pass

            async def sign_in(self, login, password):
                self._session.set_token(await self._login.login(login, password))

            def sign_out(self):
                self._session.clear_token()

            async def create_organization(self, id, name):
                return await self._crud.create("organization", {"_id": id, "name": name})

            async def organization(self, id):
                return await self._crud.get_one("organization", id)
    """,
}


async def _urllib_fetch(method, url, headers, body):
    def fetch():
        request = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return RawResponse(status=response.status, headers={}, body=response.read())
        except urllib.error.HTTPError as error:
            with error:
                return RawResponse(status=error.code, headers={}, body=error.read())

    return await asyncio.to_thread(fetch)


class UrllibFetcher:
    async def fetch(self, method, url, headers, body):
        return await _urllib_fetch(method, url, headers, body)


def _backend_is_ready():
    """the HTTP port answers before every component is validated: wait for the login service to be
    reported by the capabilities themselves"""
    try:
        with urllib.request.urlopen(f"{BASE_URL}/services/__remote_capabilities__", timeout=1) as response:
            components = json.loads(response.read())["data"].get("components", [])
    except (urllib.error.URLError, ConnectionError, ValueError):
        return False
    return any("ycappuccino.api.permissions.ILoginService" in component["provides"] for component in components)


class TestClientAgainstARealBackend(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.backend_app = TemporaryApplication(BACKEND_APPLICATION).open()
        cls.addClassCleanup(cls.backend_app.close)
        cls.backend = subprocess.Popen(
            [sys.executable, "-m", "ycappuccino.core.runner", "--root_path", cls.backend_app.root],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        cls.addClassCleanup(cls.backend.wait, 5)
        cls.addClassCleanup(cls.backend.terminate)
        if not wait_until(_backend_is_ready, timeout=15):
            raise RuntimeError("the backend subprocess was not ready in time")

        import ycappuccino.client.pyodide_transport as pyodide_transport_module

        cls.addClassCleanup(setattr, pyodide_transport_module, "pyodide_transport", pyodide_transport_module.pyodide_transport)
        pyodide_transport_module.pyodide_transport = _urllib_fetch

        cls.client_app = TemporaryApplication(CLIENT_APPLICATION).open()
        cls.addClassCleanup(cls.client_app.close)
        cls.addClassCleanup(sys.modules.pop, "generated_remote", None)
        cls.framework, cls.proxied = asyncio.run(
            bootstrap.start_client(
                "clienttest", [cls.client_app.package], properties={"client.base_url": BASE_URL},
                root=cls.client_app.root, fetcher=UrllibFetcher(), base_url=BASE_URL,
            )
        )
        cls.addClassCleanup(cls.framework.stop)
        if not wait_until(lambda: cls.framework.context.get_service_reference("Demo"), timeout=15):
            raise RuntimeError("Demo was never validated: its proxies were not injected")
        context = cls.framework.context
        cls.demo = context.get_service(context.get_service_reference("Demo"))
        cls.services = context.get_service(context.get_service_reference("IServiceEndpoint"))
        cls.transport = context.get_service(context.get_service_reference("HttpTransport"))

    def setUp(self):
        self.demo.sign_out()

    def test_discovery_proxies_the_public_interfaces_only(self):
        self.assertIn("ycappuccino.api.permissions.ILoginService", self.proxied)
        self.assertIn("ycappuccino.api.endpoints_storage.ICrud", self.proxied)
        self.assertIn("ycappuccino.api.endpoints_service.IServiceEndpoint", self.proxied)
        self.assertNotIn("ycappuccino.api.storage.IManager", self.proxied)

    def test_a_secured_use_case_refuses_an_anonymous_client(self):
        with self.assertRaises(NotAuthenticated):
            asyncio.run(self.demo.organization("anything"))

    def test_signed_in_the_client_writes_and_reads_with_its_user_rights(self):
        asyncio.run(self.demo.sign_in("superadmin", "demo"))

        asyncio.run(self.demo.create_organization("acme", "Acme"))
        organization = asyncio.run(self.demo.organization("acme"))

        self.assertEqual(organization["name"], "Acme")

    def test_wrong_credentials_are_refused(self):
        with self.assertRaises(InvalidRequest):
            asyncio.run(self.demo.sign_in("superadmin", "wrong"))

    def test_a_dataclass_result_comes_back_typed(self):
        result = asyncio.run(
            self.services.call("login", "POST", [], {}, {"login": "superadmin", "password": "demo"}, None)
        )

        self.assertIsInstance(result, ServiceResult)
        self.assertIn("token", result.body)

    def test_an_internal_interface_is_out_of_reach(self):
        with self.assertRaises(NotFound):
            asyncio.run(self.transport.dispatch("ycappuccino.api.storage.IManager", "get_many", {"item_id": "login"}))


if __name__ == "__main__":
    unittest.main()
