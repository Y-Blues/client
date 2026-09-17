"""
make_rpc_proxy: synthesizes, by reflection over a backend interface, a native component implementing
it whose every business method is one JSON-RPC call to the backend (HttpTransport.dispatch, received
by ycappuccino.remote's __remote_dispatch__). Application code depends on the interface, the framework
injects the proxy: nothing in the application knows the implementation is on the other side of HTTP.

Same technique as ycappuccino.remote.remote_proxy.make_generic_proxy, deliberately duplicated rather
than imported (client does not depend on remote): a real __init__ and real method signatures are
forged with exec, so core's describe_component introspects them like hand-written code. Two
differences: the proxy depends on HttpTransport (the session carrying the user's token) instead of a
peer address, and it never sends a `subject` -- the backend derives it from the token.

Arguments and results are JSON; a result annotated with a dataclass is rebuilt from its JSON object.
"""

import dataclasses
import inspect
import sys
import typing
from typing import Any, Callable

from ycappuccino.client.transport import HttpTransport


def make_rpc_proxy(interface: type, qualified_path: str) -> type:
    """a concrete component class implementing `interface`, calling the backend specification
    `qualified_path` ("module.ClassName", as the backend's __remote_capabilities__ reports it)"""
    namespace: dict = {
        # the framework's bundle scan only installs classes defined in the scanned module
        "__module__": sys._getframe(1).f_globals.get("__name__", __name__),
        "__init__": _build_init(),
        "_ycappuccino_qualified_path": qualified_path,
    }
    return_types = {}
    for name in _abstract_business_methods(interface):
        method = getattr(interface, name)
        namespace[name] = _build_method(name, inspect.signature(method))
        return_types[name] = _dataclass_return_type(method)
    namespace["_ycappuccino_return_types"] = return_types

    class_name = remote_class_name(interface)
    klass = type(class_name, (_RpcProxyBase, interface), namespace)
    klass.__qualname__ = class_name
    return klass


def remote_class_name(interface: type) -> str:
    name = interface.__name__
    return "Remote" + (name[1:] if name.startswith("I") and name[1:2].isupper() else name)


def _abstract_business_methods(interface: type) -> list:
    return sorted(
        name
        for name, member in inspect.getmembers(interface)
        if getattr(member, "__isabstractmethod__", False) and name not in ("start", "stop")
    )


def _dataclass_return_type(method: Callable) -> type | None:
    try:
        return_type = typing.get_type_hints(method).get("return")
    except Exception:
        return None
    return return_type if isinstance(return_type, type) and dataclasses.is_dataclass(return_type) else None


def _build_init() -> Callable:
    source = "def __init__(self, transport: _HttpTransport):\n    self._transport = transport\n"
    namespace = {"_HttpTransport": HttpTransport}
    exec(source, namespace)  # noqa: S102 - controlled source
    return namespace["__init__"]


def _build_method(name: str, signature: inspect.Signature) -> Callable:
    parameters = list(signature.parameters.values())[1:]
    arguments = []
    sent = []
    namespace: dict = {}
    for parameter in parameters:
        if parameter.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        if parameter.default is inspect.Parameter.empty:
            arguments.append(parameter.name)
        else:
            namespace[f"_default_{parameter.name}"] = parameter.default
            arguments.append(f"{parameter.name}=_default_{parameter.name}")
        if parameter.name != "subject":
            sent.append(f"{parameter.name!r}: {parameter.name}")
    source = (
        f"async def {name}(self, {', '.join(arguments)}):\n"
        f"    return await self._call({name!r}, {{{', '.join(sent)}}})\n"
    )
    exec(source, namespace)  # noqa: S102 - controlled source
    return namespace[name]


class _RpcProxyBase:
    _ycappuccino_qualified_path = ""
    _ycappuccino_return_types: dict = {}

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def _call(self, method_name: str, kwargs: dict) -> Any:
        result = await self._transport.dispatch(self._ycappuccino_qualified_path, method_name, kwargs)
        return_type = self._ycappuccino_return_types.get(method_name)
        if return_type is not None and isinstance(result, dict):
            return return_type(**result)
        return result
