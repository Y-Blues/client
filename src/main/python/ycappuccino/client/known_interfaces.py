"""
KNOWN_INTERFACES: the single, well-documented place to extend "which api-level interfaces this
client knows how to proxy over HTTP" - see
client/docs/superpowers/specs/2026-09-15-client-design.md §9.1 (why `resource`, the HTTP mount
prefix, is the one deliberate per-interface datum make_remote() needs - a fact no reflection over
method/parameter names can derive) and §10 (the discovery-gated codegen built on top of this table,
and the honest boundary it does NOT lift: `client` can only ever proxy an interface that also has a
known http_server wire shape - the four below are the only ones that exist today).

`ycappuccino/client/components.py` (today's unconditional four, used when backend discovery is
unavailable) and `ycappuccino/client/discovery.py` (discovery-gated codegen, used when it succeeds)
both build their Remote* classes from this SAME table - there was, before this file existed, a real
risk of the two drifting out of sync (a fifth interface added to one but not the other). Adding a
real fifth well-known api-level interface, once http_server grows an HTTP mount for it, means
adding ONE entry here - nowhere else.
"""

from ycappuccino.api.endpoints_service import IServiceEndpoint
from ycappuccino.api.endpoints_storage import ICrud, IDrafts, IItemCatalog

# (interface, resource, extra_deps): resource is the one-word HTTP mount prefix (spec §9.1);
# extra_deps are the additional named+typed constructor dependencies make_remote() must forge
# (catalog=IItemCatalog, for ICrud/IDrafts's item_id -> plural resolution, spec §9.3).
KNOWN_INTERFACES = (
    (ICrud, "crud", {"catalog": IItemCatalog}),
    (IDrafts, "drafts", {"catalog": IItemCatalog}),
    (IItemCatalog, "items", {}),
    (IServiceEndpoint, "services", {}),
)


def remote_class_name(interface: type) -> str:
    """"Remote" + the interface's own name, minus its leading "I" if it has one - the same naming
    convention components.py's four hand-picked names (RemoteCrud, RemoteDrafts, ...) already
    followed; factored out so discovery.py's generated modules use it identically."""
    name = interface.__name__
    return "Remote" + (name[1:] if name.startswith("I") else name)
