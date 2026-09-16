"""
The four Remote* components, synthesized (not hand-written - see remote_proxy.py and
client/docs/superpowers/specs/2026-09-15-client-design.md §9) and assigned at module level, so
Framework.load_bundles()'s per-module class scan (Framework._install_module, which filters on
klass.__module__ == module.__name__) auto-discovers them as native YCappuccinoComponent
subclasses exactly as if they had been written by hand in this file - the moment bundle_prefix
includes "ycappuccino.client", app code gets working ICrud/IDrafts/IItemCatalog/IServiceEndpoint
implementations with zero code of its own naming this module.

"crud"/"drafts"/"items"/"services" are the one deliberate per-interface datum this design keeps
(the HTTP mount prefix - see spec §9.1 for why this one fact cannot be derived by reflection and
is not the declarative route table the user asked to eliminate). catalog=IItemCatalog is the
extra constructor dependency RemoteCrud/RemoteDrafts need to resolve item_id -> plural (spec §9.3);
it resolves, through the real DI container, to RemoteItemCatalog below - itself auto-discovered
the same way, with no explicit wiring anywhere.
"""

from ycappuccino.api.endpoints_service import IServiceEndpoint
from ycappuccino.api.endpoints_storage import ICrud, IDrafts, IItemCatalog
from ycappuccino.client.remote_proxy import make_remote

RemoteCrud = make_remote(ICrud, "crud", catalog=IItemCatalog)
RemoteDrafts = make_remote(IDrafts, "drafts", catalog=IItemCatalog)
RemoteItemCatalog = make_remote(IItemCatalog, "items")
RemoteServiceEndpoint = make_remote(IServiceEndpoint, "services")
