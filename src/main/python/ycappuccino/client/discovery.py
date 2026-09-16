"""
Backend component discovery, resolved BEFORE Framework.init() is ever called - see
client/docs/superpowers/specs/2026-09-15-client-design.md §10 for the full design and its honest
limits. This module answers two separate questions.

1. CAN `client` discover, over HTTP, which api-level interfaces the backend actually has loaded?

Only by CONVENTION, never by contract. `discover_backend_provides` below calls a service literally
named "__remote_capabilities__" through the ALREADY-GENERIC "/api/services/<name>" route - the
same route RemoteServiceEndpoint always used, zero special-casing needed to call ANY named
service, generically, exactly like calling any other service by name. If the backend does not
load `ycappuccino.remote` (out of this repo's scope, being extended in parallel), or has not wired
a service under that exact name, the call fails (NotFound, or any other error) and this module
reports "unknown" (`None`) - callers then fall back to today's unconditional four Remote*, entirely
unchanged (see components.py). This is a REAL, undocumented-elsewhere-except-by-convention coupling
between `client` and whatever the backend happens to load: `client` does not import
`ycappuccino.remote`, does not know its actual shape, and this repo has no authority over what
`remote`'s own agent ships. If that name or the assumed response shape (see `_extract_provides`)
ever changes, discovery degrades silently to the fallback - which is the intended, safe failure
mode, not a bug to paper over.

2. Given that list, HOW does `client` turn it into "create only the proxies the backend has",
without the reentrancy/timing hazard core/README.md documents under "Introspecter les composants
natifs installés" ("Piège de timing" - calling instantiate_component() from a component's own
start(), even off a background thread as ycappuccino-component-creator's ComponentActivator.start()
does to avoid the OTHER, worse deadlock hazard, gives NO guarantee the created instances exist
before load_bundles() finishes its single bundle_prefix scanning pass)?

ANSWER CHOSEN HERE: never call instantiate_component() at all, and never discover from inside a
component's start(). `client`'s browser bootstrap (static/main.py) already does async setup
(Pyodide/micropip installs, virtual-filesystem writes) BEFORE calling Framework().init() - a
capability a `bundle_prefix`-scanned server package (or `remote`'s own peer-to-peer discovery,
forced to react to already-running processes) does not have. This module's discovery HTTP call
happens in that same pre-init window, using a plain, hand-constructed HttpTransport +
RemoteServiceEndpoint (no Pelix, no DI at all - exactly the pattern this repo's own
component-level unit tests already use, see core/README.md "Tester ses composants"), and its
result is used to WRITE an ordinary, static-looking native-component module
(`write_generated_module` below) into the application's own bundle package - a file
Framework.load_bundles()'s completely normal, un-hacked bundle_prefix scan then picks up exactly
like any hand-written module. Nothing dynamic happens DURING or AFTER the scan: no
instantiate_component(), no background thread, no reentrancy, hence NONE of core's timing hazard
applies to this file at all. This is deliberately NOT the dynamic-instantiate-from-start() pattern
component-creator uses (and that `remote`'s agent is reportedly forced into for backend-to-backend
peers, which cannot pre-run arbitrary Python before their own bundle_prefix scan the way a
browser's own bootstrap script can) - that pattern was considered and rejected for this repo
specifically because the honest alternative above sidesteps the hazard entirely rather than living
with it.

REAL BOUNDARY (spec §10; see remote_proxy.py's own module docstring for the deeper reason): only
the four interfaces in `known_interfaces.KNOWN_INTERFACES` can EVER be proxied this way, discovered
or not. `client`'s reflection convention (HTTP verb from method name, path from parameter names) is
tied to `http_server`'s specific "/api/crud|drafts|items|services" wire protocol, which exists ONLY
for these four interfaces. A genuinely arbitrary custom app interface the backend happens to report
via "__remote_capabilities__" has NO discoverable HTTP shape for `client` to reflect against -
proxying it correctly would need `http_server` to grow a generic RPC route (mirroring what
`remote`'s peer-to-peer dispatcher can do, because BOTH sides there are Python processes able to
run a generic RPC dispatcher; a browser calling `http_server`'s REST API has no such route
available). That is a real, legitimate, unimplemented `http_server`-level follow-up - NOT something
achievable from `client` alone, and NOT built here: `enabled_known_interfaces` below silently drops
any discovered specification that is not already in `KNOWN_INTERFACES`, on purpose.
"""

import os
from typing import Optional

from ycappuccino.api.endpoints_service import IServiceEndpoint
from ycappuccino.client.known_interfaces import KNOWN_INTERFACES, remote_class_name
from ycappuccino.client.remote_proxy import make_remote
from ycappuccino.client.transport import HttpTransport, IHttpFetcher

from ycappuccino.core.component_factory import resolve_class

CAPABILITIES_SERVICE_NAME = "__remote_capabilities__"

_GENERATED_MODULE_HEADER = (
    '"""Generated by ycappuccino.client.discovery - see design spec section 10. Not hand-written; '
    'safe to regenerate; never edited by hand."""\n'
)


async def discover_backend_provides(
    fetcher: Optional[IHttpFetcher] = None, base_url: Optional[str] = None
) -> Optional[set]:
    """
    Best-effort: builds a plain HttpTransport + a plain RemoteServiceEndpoint BY HAND (no Pelix, no
    DI - see module docstring point 2) and calls "__remote_capabilities__" through the existing
    generic "/api/services/<name>" route. Returns the set of fully-qualified dotted "provides"
    paths the backend reports (mirroring core.framework.Framework.list_components()'s own shape -
    see `_extract_provides`), or None on ANY failure whatsoever: wrong/missing service (NotFound),
    a network error, a malformed response. None is the caller's signal to fall back to today's
    unconditional four (see `enabled_known_interfaces`) - never a partial/best-guess result.
    """
    transport = HttpTransport(fetcher=fetcher)
    if base_url is not None:
        # bootstrap-time convenience: no framework/IConfiguration exists yet to read
        # "client.base_url" from at this point (see spec §2 A.3) - discovery runs before
        # Framework().init() is even called.
        transport._base_url = base_url
    remote_service_endpoint_cls = make_remote(IServiceEndpoint, "services")
    service_endpoint = remote_service_endpoint_cls(transport)
    try:
        result = await service_endpoint.call(CAPABILITIES_SERVICE_NAME, "POST", [], {}, {}, subject=None)
    except Exception:
        return None
    return _extract_provides(getattr(result, "body", None))


def _extract_provides(body) -> Optional[set]:
    """
    ASSUMED shape (convention, not contract - see module docstring point 1): `body` mirrors
    Framework.list_components()'s own list of {"module", "class", "provides"} dicts (the natural
    shape for a "__remote_capabilities__" service that just returns
    Framework.get_framework().list_components() verbatim - not verified against any real `remote`
    implementation, since `remote` is out of this repo's scope). Any other shape is treated as a
    failed discovery (None), never a partial/best-guess result.
    """
    try:
        provides: set = set()
        for entry in body:
            provides.update(entry["provides"])
        return provides
    except (TypeError, KeyError):
        return None


def enabled_known_interfaces(discovered_provides: Optional[set]) -> list:
    """
    discovered_provides is None (discovery unavailable) -> ALL known interfaces: today's
    unconditional behaviour, byte-for-byte unchanged. Otherwise: only the known interfaces the
    backend actually reports, resolved back to a real class via
    core.component_factory.resolve_class (the same function core/README.md documents for turning a
    `provides` qualified path back into a class) and matched against
    known_interfaces.KNOWN_INTERFACES by identity. A discovered path that resolve_class can't
    import, or that resolves to something outside KNOWN_INTERFACES, is silently dropped - see
    module docstring's "REAL BOUNDARY" for why that second case is not a bug.
    """
    if discovered_provides is None:
        return list(KNOWN_INTERFACES)
    resolved = set()
    for path in discovered_provides:
        try:
            resolved.add(resolve_class(path))
        except Exception:
            continue
    return [spec for spec in KNOWN_INTERFACES if spec[0] in resolved]


def generated_module_source(enabled_specs: list) -> str:
    """the exact source of the module write_generated_module() writes - a plain, static-looking
    ycappuccino.client.remote_proxy.make_remote(...) call per entry of `enabled_specs`, imports
    inferred generically from each involved class's own __module__ (never hardcoded), so this
    keeps working unchanged if known_interfaces.KNOWN_INTERFACES ever gains a fifth entry living in
    a different api module."""
    classes_needed: set = set()
    for interface, _resource, extra_deps in enabled_specs:
        classes_needed.add(interface)
        classes_needed.update(extra_deps.values())

    imports_by_module: dict = {}
    for klass in classes_needed:
        imports_by_module.setdefault(klass.__module__, set()).add(klass.__name__)

    lines = [_GENERATED_MODULE_HEADER, ""]
    for module_name in sorted(imports_by_module):
        lines.append(f"from {module_name} import {', '.join(sorted(imports_by_module[module_name]))}")
    lines.append("from ycappuccino.client.remote_proxy import make_remote")
    lines.append("")
    for interface, resource, extra_deps in enabled_specs:
        extras = "".join(f", {name}={dep.__name__}" for name, dep in extra_deps.items())
        lines.append(f"{remote_class_name(interface)} = make_remote({interface.__name__}, {resource!r}{extras})")
    return "\n".join(lines) + "\n"


def write_generated_module(enabled_specs: list, file_path: str) -> None:
    """writes generated_module_source(enabled_specs) to file_path - a plain open(path, "w"), the
    same technique static/main.py already uses to write conf/application.yml into Pyodide's
    virtual filesystem (spec §0bis(c)), so this works identically under Pyodide or plain CPython."""
    directory = os.path.dirname(file_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(file_path, "w") as file:
        file.write(generated_module_source(enabled_specs))


def without_client_components(bundle_prefix: list) -> list:
    """
    Replaces the whole "ycappuccino.client" package entry with just "ycappuccino.client.transport"
    (HttpTransport - never conditional, still needed by every generated Remote*) in a bundle_prefix
    list. Once a generated module (write_generated_module, above) has decided which Remote* to
    create, "ycappuccino.client.components" (the unconditional four) must NOT also be scanned, or
    both would register an implementation of the same interface and collide - see discovery.py's
    own module docstring and design spec §10. A bundle_prefix entry that isn't literally
    "ycappuccino.client" is passed through unchanged.
    """
    return ["ycappuccino.client.transport" if entry == "ycappuccino.client" else entry for entry in bundle_prefix]


async def prepare_generated_module(
    file_path: str, fetcher: Optional[IHttpFetcher] = None, base_url: Optional[str] = None
) -> list:
    """
    Convenience orchestration for a bootstrap (static/main.py, or a test): runs discovery, writes
    the generated module at file_path, and returns the list of HTTP mount resources ("crud",
    "items", ...) that ended up enabled - purely informational (e.g. status text), the generated
    module on disk is the actual result callers act on.
    """
    discovered = await discover_backend_provides(fetcher=fetcher, base_url=base_url)
    enabled = enabled_known_interfaces(discovered)
    write_generated_module(enabled, file_path)
    return [resource for _interface, resource, _extra_deps in enabled]
