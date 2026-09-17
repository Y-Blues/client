"""
remote_proxy.make_remote: generic, reflection-based factory that synthesizes a concrete
YCappuccinoComponent subclass implementing every abstract method of a given api interface
(ICrud, IDrafts, IItemCatalog, IServiceEndpoint, or any future interface of the same shape),
dispatching each call over an injected HttpTransport - purely from the METHOD NAME and
PARAMETER NAMES of the interface being implemented. No per-method route table, no hand-written
method body per interface: see client/docs/superpowers/specs/2026-09-15-client-design.md §9 for
the five conventions this implements verbatim, worked out against http_server's real routes
(ApiServlet source, not just its README), and their honestly-documented limitations - read that
before touching this file, especially §9.4 (where pure reflection is genuinely weaker than a
declarative route table would have been).

Only one datum per interface survives here, and it is documented in §9.1 as a deliberate,
minimal exception to "zero per-interface data": `resource`, the one-word HTTP mount prefix
("crud", "drafts", "items", "services") - a deployment fact no method/parameter name can encode
reliably, categorically different from a per-method route table.
"""

import inspect
import sys
from typing import Any, Callable

from ycappuccino.api.endpoints_service import ServiceResult
from ycappuccino.api.endpoints_storage import NotFound
from ycappuccino.client.transport import HttpTransport, decode_envelope

# Convention 3: a method whose parameters include either of these two names is already
# HTTP-shaped - these two are the only names in the whole vocabulary that are NEVER used
# generically elsewhere (unlike "params"/"body", which ICrud/IDrafts also use for their own,
# differently-shaped query/body parameters): their mere presence is what triggers the literal
# override, not "params"/"body" alone.
_LITERAL_TRIGGER_NAMES = {"method", "extra_path"}
# Once triggered, these four parameter names all take their literal runtime VALUE (verb/extra
# path/query/body), never inferred from the method's own name.
_LITERAL_OVERRIDE_NAMES = {"method", "extra_path", "params", "body"}

# Convention 1/2: method names whose HTTP shape is fully disambiguated by verb + argument shape
# alone, never needing a name-derived path suffix.
_STANDARD_NAMES = {"get_one", "get_many", "get_items", "create", "update", "delete", "delete_many", "save"}


def make_remote(interface: type, resource: str, **extra_deps: type) -> type:
    """
    Synthesize a concrete implementation of `interface` (an abstract YCappuccinoComponent
    interface from ycappuccino.api), backed by HttpTransport under the "/<resource>/..." mount.
    `extra_deps` declares any additional constructor dependencies the synthesized class needs
    (e.g. catalog=IItemCatalog for ICrud/IDrafts's item_id -> plural resolution, see spec §9.3):
    each becomes a properly-named, properly-typed constructor parameter, so core's real DI
    (describe_component/create_factory_module, which introspects inspect.signature by name and
    typing.get_type_hints by annotation) injects it exactly like a hand-written component would.
    """
    caller_module = sys._getframe(1).f_globals.get("__name__", __name__)

    method_names = _abstract_business_methods(interface)
    bulk_method_name = _find_bulk_method(interface, method_names)
    identity_keyword = _identity_keyword(bulk_method_name) if bulk_method_name else None

    namespace: dict = {
        "__module__": caller_module,
        "_ycappuccino_resource": resource,
        "_ycappuccino_bulk_method_name": bulk_method_name,
        "_ycappuccino_identity_keyword": identity_keyword,
    }
    for name in method_names:
        signature = inspect.signature(getattr(interface, name))
        namespace[name] = _build_method(name, signature)
    namespace["__init__"] = _build_init(extra_deps)

    class_name = "Remote" + (interface.__name__[1:] if interface.__name__.startswith("I") else interface.__name__)
    klass = type(class_name, (_RemoteProxyBase, interface), namespace)
    klass.__qualname__ = class_name
    return klass


# ---------------------------------------------------------------------------- class building


def _abstract_business_methods(interface: type) -> list:
    """the interface's own abstract methods, alphabetically (deterministic), excluding the
    YCappuccinoComponent lifecycle methods (start/stop), which _RemoteProxyBase implements"""
    return sorted(
        name
        for name, member in inspect.getmembers(interface)
        if getattr(member, "__isabstractmethod__", False) and name not in ("start", "stop")
    )


def _find_bulk_method(interface: type, method_names: list) -> str | None:
    """convention 4: the get_* method whose every parameter (besides self) has a default -
    the interface's "fetch the whole collection" accessor, if it has one"""
    for name in method_names:
        if not name.startswith("get_"):
            continue
        parameters = list(inspect.signature(getattr(interface, name)).parameters.values())[1:]
        if all(parameter.default is not inspect.Parameter.empty for parameter in parameters):
            return name
    return None


def _identity_keyword(bulk_method_name: str) -> str:
    """naive singularization of the bulk accessor's own name (get_items -> item) - documented
    as fragile (does not generalize to an irregular plural), see spec §9.4"""
    remainder = bulk_method_name[len("get_"):] if bulk_method_name.startswith("get_") else bulk_method_name
    return remainder[:-1] if remainder.endswith("s") else remainder


def _build_init(extra_deps: dict) -> Callable:
    """forges a REAL, introspectable __init__ (real parameter names, real type annotations -
    not a **kwargs sink) via exec, the same technique dataclasses/attrs/namedtuple use - see
    spec §9.2. describe_component (core/component_factory.py) inspects this by name/annotation,
    exactly like a hand-written component's constructor."""
    dep_names = list(extra_deps.keys())
    params = ["self", "transport: _T_transport"] + [f"{name}: _T_{name}" for name in dep_names]
    body = ["    self._transport = transport"] + [f"    self._{name} = {name}" for name in dep_names]
    source = f"def __init__({', '.join(params)}):\n" + "\n".join(body) + "\n"

    namespace = {"_T_transport": HttpTransport}
    namespace.update({f"_T_{name}": dep_type for name, dep_type in extra_deps.items()})
    exec(source, namespace)  # noqa: S102 - controlled source, built entirely from trusted inputs
    return namespace["__init__"]


def _build_method(name: str, signature: inspect.Signature) -> Callable:
    """forges a method with the SAME calling convention as the interface's own abstract method
    (same parameter names/defaults, so callers positionally/by-keyword exactly as they would a
    hand-written component), whose body only ever calls self._dispatch(name, {param: value})"""
    parameters = list(signature.parameters.values())[1:]  # drop self
    arg_srcs = []
    dict_items = []
    namespace: dict = {}
    for parameter in parameters:
        if parameter.default is inspect.Parameter.empty:
            arg_srcs.append(parameter.name)
        else:
            default_name = f"_default_{parameter.name}"
            namespace[default_name] = parameter.default
            arg_srcs.append(f"{parameter.name}={default_name}")
        dict_items.append(f"{parameter.name!r}: {parameter.name}")
    source = (
        f"async def {name}(self, {', '.join(arg_srcs)}):\n"
        f"    return await self._dispatch({name!r}, {{{', '.join(dict_items)}}})\n"
    )
    exec(source, namespace)  # noqa: S102 - controlled source, built entirely from trusted inputs
    return namespace[name]


# ---------------------------------------------------------------------------- runtime dispatch


class _RemoteProxyBase:
    """
    mixed into every class make_remote() builds; provides start()/stop() (convention 4's
    collection caching) and _dispatch() (conventions 1/2/3/5). Never used on its own.
    """

    _ycappuccino_resource = ""
    _ycappuccino_bulk_method_name = None
    _ycappuccino_identity_keyword = None
    _ycappuccino_cache = None

    async def start(self) -> None:
        if self._ycappuccino_bulk_method_name:
            response = await self._transport.request("GET", f"/{self._ycappuccino_resource}")
            envelope = decode_envelope(response)
            self._ycappuccino_cache = list(envelope["data"])

    async def stop(self) -> None:
        pass

    async def _dispatch(self, method_name: str, kwargs: dict) -> Any:
        kwargs = dict(kwargs)
        kwargs.pop("subject", None)  # spec §2 A.1: accepted for signature parity, never used

        if _LITERAL_TRIGGER_NAMES & kwargs.keys():
            return await self._dispatch_literal(kwargs)

        if method_name == self._ycappuccino_bulk_method_name:
            return list(self._ycappuccino_cache or [])

        if self._ycappuccino_identity_keyword:
            field = _cache_lookup_field(method_name, self._ycappuccino_identity_keyword)
            if field is not None:
                return self._cache_lookup(method_name, field, kwargs)

        return await self._dispatch_http(method_name, kwargs)

    async def _dispatch_http(self, method_name: str, kwargs: dict) -> Any:
        verb = _infer_verb(method_name)
        segments = [self._ycappuccino_resource]
        query: dict = {}
        body = None

        for name, value in kwargs.items():
            if name == "item_id":
                segments.append(await self._resolve_plural(value))
            elif name in ("id", "draft"):
                if value is not None:
                    segments.append(str(value))
            elif name == "filter":
                if value is not None:
                    query["filter"] = value
            elif name in ("fields", "body"):
                body = value
            elif name == "params":
                if value:
                    query.update(value)
            elif value is not None:
                segments.append(str(value))

        suffix = _suffix_for(method_name, verb)
        if suffix:
            segments.append(suffix)

        path = "/" + "/".join(segment.strip("/") for segment in segments if segment)
        response = await self._transport.request(verb, path, params=query or None, body=body)
        envelope = decode_envelope(response)
        return _shape_result(method_name, envelope)

    async def _dispatch_literal(self, kwargs: dict) -> ServiceResult:
        """convention 3: method/extra_path/params/body are used as literal values, never
        inferred from the method's own name"""
        verb = kwargs.get("method") or "POST"
        extra_path = kwargs.get("extra_path") or []
        params = kwargs.get("params") or None
        body = kwargs.get("body")

        segments = [self._ycappuccino_resource]
        for name, value in kwargs.items():
            if name in _LITERAL_OVERRIDE_NAMES:
                continue
            if value is not None:
                segments.append(str(value))
        segments.extend(str(segment) for segment in extra_path)

        path = "/" + "/".join(segment.strip("/") for segment in segments if segment)
        response = await self._transport.request(verb, path, params=params, body=body)
        envelope = decode_envelope(response)
        return ServiceResult(body=envelope["data"])

    def _cache_lookup(self, method_name: str, field: str, kwargs: dict) -> Any:
        value = next(iter(kwargs.values()), None)
        item = self._lookup_cache(field, value)
        if item is None:
            raise NotFound(f"unknown {field} {value!r}")
        return item

    def _lookup_cache(self, field: str, value: Any) -> dict | None:
        for item in self._ycappuccino_cache or []:
            if item.get(field) == value:
                return item
        return None

    async def _resolve_plural(self, item_id: str) -> str:
        catalog = getattr(self, "_catalog", None)
        if catalog is not None:
            item = await catalog.get_item(item_id)
            return item["plural"]
        if self._ycappuccino_cache is not None:
            item = self._lookup_cache("id", item_id)
            if item is None:
                raise NotFound(f"unknown item {item_id!r}")
            return item["plural"]
        raise RuntimeError(
            f"{type(self).__name__}: cannot resolve item_id {item_id!r} to a plural - no "
            "IItemCatalog dependency injected (extra_deps=catalog=...) and this proxy has no "
            "own cached collection either (see make_remote's convention 4)"
        )


def _infer_verb(method_name: str) -> str:
    """convention 1"""
    if method_name.startswith("get"):
        return "GET"
    if method_name in ("update", "save"):
        return "PUT"
    if method_name.startswith("delete") or method_name == "discard":
        return "DELETE"
    return "POST"  # create, publish, and any other unrecognized action


def _suffix_for(method_name: str, verb: str) -> str | None:
    """convention 2's trailing segment: never for a standard CRUD-shaped name or a
    DELETE/PUT verb (already disambiguated by verb + argument shape alone - this is exactly
    what keeps `discard` route-compatible with `save`/`get_one`, see spec §9.3)"""
    if method_name in _STANDARD_NAMES or verb in ("DELETE", "PUT"):
        return None
    if verb == "GET":
        return method_name[len("get_"):] if method_name.startswith("get_") else method_name
    return method_name  # POST (e.g. "publish")


def _cache_lookup_field(method_name: str, identity_keyword: str) -> str | None:
    """convention 4: get_<identity> -> lookup by "id"; get_<identity>_by_<field> -> lookup by
    <field> (parsed from the method's own name, never hardcoded)"""
    if not method_name.startswith("get_"):
        return None
    remainder = method_name[len("get_"):]
    if remainder == identity_keyword:
        return "id"
    prefix = identity_keyword + "_by_"
    if remainder.startswith(prefix):
        return remainder[len(prefix):]
    return None


def _shape_result(method_name: str, envelope: dict) -> Any:
    """convention 5"""
    if method_name == "get_many":
        data = envelope["data"]
        return {"items": data, "total": envelope["meta"].get("size", len(data))}
    if method_name == "delete_many":
        return envelope["data"]["deleted"]
    if method_name in ("delete", "discard"):
        return None
    return envelope["data"]
