"""
RemoteItemCatalog: browser-side IItemCatalog, backed by GET /api/items... on the real backend.

Fetches the item list once, at start() (no hot reload - same deliberate simplification as
scheduler/hosts, see their READMEs), and caches it: get_items()/get_item()/get_item_by_plural()
never make a network call. get_schema()/get_empty() are not part of the public list view
(http_server/README.md), so they hit the network every call.

This component is never constructed by app code (see client/README.md): it is auto-discovered,
like every Remote* component here, the moment bundle_prefix includes ycappuccino.client - exactly
like including ycappuccino.storage gives an application a working IManager without it ever naming
MemoryStorage/Manager. App code depends on IItemCatalog, never on this class.
"""

from typing import Optional

from ycappuccino.api.endpoints_storage import IItemCatalog, NotFound
from ycappuccino.client.transport import HttpTransport, decode_envelope


class RemoteItemCatalog(IItemCatalog):

    def __init__(self, transport: HttpTransport):
        self._transport = transport
        self._items: list = []
        self._by_id: dict = {}
        self._by_plural: dict = {}

    async def start(self):
        response = await self._transport.request("GET", "/items")
        envelope = decode_envelope(response)
        self._items = list(envelope["data"])
        self._by_id = {item["id"]: item for item in self._items}
        self._by_plural = {item["plural"]: item for item in self._items}

    async def stop(self):
        pass

    async def get_items(self, subject: Optional[dict] = None) -> list:
        return list(self._items)

    async def get_item(self, item_id: str, subject: Optional[dict] = None) -> dict:
        item = self._by_id.get(item_id)
        if item is None:
            raise NotFound(f"unknown item {item_id!r}")
        return item

    async def get_item_by_plural(self, plural: str, subject: Optional[dict] = None) -> dict:
        item = self._by_plural.get(plural)
        if item is None:
            raise NotFound(f"unknown item plural {plural!r}")
        return item

    async def get_schema(self, item_id: str, subject: Optional[dict] = None) -> dict:
        plural = (await self.get_item(item_id))["plural"]
        response = await self._transport.request("GET", f"/items/{plural}/schema")
        return decode_envelope(response)["data"]

    async def get_empty(self, item_id: str, subject: Optional[dict] = None) -> Optional[dict]:
        plural = (await self.get_item(item_id))["plural"]
        response = await self._transport.request("GET", f"/items/{plural}/empty")
        return decode_envelope(response)["data"]
