"""make_rpc_proxy against a fake HttpTransport: the synthesized class implements the interface, calls
HttpTransport.dispatch with the method's own arguments, never sends a subject, and rebuilds a dataclass
return value. The real wire (dispatch -> http_server -> __remote_dispatch__) is proven end to end by
test_client_framework.py."""

import abc
import dataclasses
import inspect
import unittest

from ycappuccino.api.core_base import YCappuccinoComponent
from ycappuccino.client.rpc_proxy import make_rpc_proxy
from ycappuccino.client.transport import HttpTransport
from ycappuccino.core.component_factory import describe_component

QUALIFIED_PATH = "somewhere.IInventory"


@dataclasses.dataclass
class Receipt:
    event: str
    count: int


class IInventory(YCappuccinoComponent, abc.ABC):

    @abc.abstractmethod
    async def check(self, sku: str, warehouse: str = "main", subject: dict | None = None) -> int:
        """units in stock"""

    @abc.abstractmethod
    async def last(self) -> Receipt:
        """the last receipt"""


class FakeTransport:
    def __init__(self, result=None):
        self.result = result
        self.calls = []

    async def dispatch(self, qualified_path, method_name, kwargs):
        self.calls.append((qualified_path, method_name, kwargs))
        return self.result


class TestMakeRpcProxy(unittest.IsolatedAsyncioTestCase):

    async def test_a_call_is_dispatched_with_its_arguments_and_defaults(self):
        transport = FakeTransport(result=12)
        proxy = make_rpc_proxy(IInventory, QUALIFIED_PATH)(transport)

        result = await proxy.check("widget")

        self.assertEqual(result, 12)
        self.assertEqual(transport.calls, [(QUALIFIED_PATH, "check", {"sku": "widget", "warehouse": "main"})])

    async def test_a_subject_is_never_sent(self):
        transport = FakeTransport()
        proxy = make_rpc_proxy(IInventory, QUALIFIED_PATH)(transport)

        await proxy.check("widget", subject={"sub": "mallory"})

        self.assertNotIn("subject", transport.calls[0][2])

    async def test_a_dataclass_return_value_is_rebuilt(self):
        proxy = make_rpc_proxy(IInventory, QUALIFIED_PATH)(FakeTransport(result={"event": "login", "count": 2}))

        self.assertEqual(await proxy.last(), Receipt("login", 2))

    async def test_lifecycle_methods_do_nothing(self):
        proxy = make_rpc_proxy(IInventory, QUALIFIED_PATH)(FakeTransport())

        await proxy.start()
        await proxy.stop()

    def test_the_class_is_a_concrete_implementation_named_after_the_interface(self):
        proxy_class = make_rpc_proxy(IInventory, QUALIFIED_PATH)

        self.assertTrue(issubclass(proxy_class, IInventory))
        self.assertFalse(inspect.isabstract(proxy_class))
        self.assertEqual(proxy_class.__name__, "RemoteInventory")

    def test_the_class_belongs_to_the_module_that_created_it(self):
        # the framework only installs the classes defined in the module it scans
        self.assertEqual(make_rpc_proxy(IInventory, QUALIFIED_PATH).__module__, __name__)

    def test_the_framework_injects_the_transport(self):
        description = describe_component(make_rpc_proxy(IInventory, QUALIFIED_PATH))

        self.assertEqual([(r.field, r.specification) for r in description.requires], [("transport", HttpTransport.__name__)])
        self.assertIn("IInventory", description.provides)


if __name__ == "__main__":
    unittest.main()
