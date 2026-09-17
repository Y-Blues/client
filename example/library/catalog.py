"""
Catalog: demo native component proving the DI wiring end-to-end. It depends on ICrud and
IItemCatalog exactly like a server-side component would (compare endpoints_storage/README.md's
own `Shelf` example) - it never imports anything from ycappuccino.client, and never constructs
RemoteCrud/RemoteItemCatalog itself. Whatever package provides those interfaces is none of its
business: on a real backend that would be ycappuccino.endpoints_storage's own Crud/ItemCatalog, in
the browser bundle they are ycappuccino.client's generated JSON-RPC proxies - see client/README.md.

`items` is populated at start() and simply printed: this is the smallest possible proof that the
chain "app component -> ICrud/IItemCatalog -> proxy -> HttpTransport -> __remote_dispatch__ -> real backend"
actually resolves through the real framework's DI, not a demonstration of a real UI.
"""

from ycappuccino.api.core_base import YCappuccinoComponent
from ycappuccino.api.endpoints_storage import ICrud, IItemCatalog


class Catalog(YCappuccinoComponent):

    def __init__(self, crud: ICrud, catalog: IItemCatalog):
        self._crud = crud
        self._catalog = catalog
        self.items = None  # populated by start(); read by tests

    async def start(self):
        self.items = await self._catalog.get_items()
        print(f"Catalog: {len(self.items)} item(s): {[item['id'] for item in self.items]}")

    async def stop(self):
        pass
