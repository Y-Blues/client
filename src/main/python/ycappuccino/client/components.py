"""
The four Remote* components, synthesized (not hand-written - see remote_proxy.py and
client/docs/superpowers/specs/2026-09-15-client-design.md §9) and assigned at module level, so
Framework.load_bundles()'s per-module class scan (Framework._install_module, which filters on
klass.__module__ == module.__name__) auto-discovers them as native YCappuccinoComponent
subclasses exactly as if they had been written by hand in this file - the moment bundle_prefix
includes "ycappuccino.client", app code gets working ICrud/IDrafts/IItemCatalog/IServiceEndpoint
implementations with zero code of its own naming this module.

This module is the UNCONDITIONAL fallback: always all four, regardless of what the backend
actually has loaded - exactly today's pre-discovery behaviour, byte-for-byte unchanged (see
discovery.py's own module docstring, §10 of the spec, for the discovery-GATED alternative used
when a backend exposes "__remote_capabilities__": that path builds a SMALLER, generated sibling
module instead of this one, and excludes this module from bundle_prefix so the two never both
register the same interface).

known_interfaces.KNOWN_INTERFACES is the single, well-documented table both this module and
discovery.py build their Remote* classes from (added to make the table itself trivially
extensible, spec §10; this loop replaces four hand-written module-level assignments with
equivalent generated ones - same classes, same names, same make_remote() calls, in the same
order - no behavioural change, verified by the pre-existing test suite, unmodified).
"""

from ycappuccino.client.known_interfaces import KNOWN_INTERFACES, remote_class_name
from ycappuccino.client.remote_proxy import make_remote

for _interface, _resource, _extra_deps in KNOWN_INTERFACES:
    globals()[remote_class_name(_interface)] = make_remote(_interface, _resource, **_extra_deps)
del _interface, _resource, _extra_deps
