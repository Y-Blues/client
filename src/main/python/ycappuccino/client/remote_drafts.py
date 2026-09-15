"""
RemoteDrafts: browser-side IDrafts, translating every call to the /api/drafts/<plural>... routes
http_server exposes (http_server/README.md). Same item_id -> plural resolution via IItemCatalog,
and the same subject-is-ignored decision, as RemoteCrud (remote_crud.py) - see its docstring for
the rationale; not repeated here to avoid drift between two copies of the same explanation.
"""

from typing import Optional

from ycappuccino.api.endpoints_storage import IDrafts, IItemCatalog
from ycappuccino.client.transport import HttpTransport, decode_envelope


class RemoteDrafts(IDrafts):

    def __init__(self, transport: HttpTransport, catalog: IItemCatalog):
        self._transport = transport
        self._catalog = catalog

    async def start(self):
        pass

    async def stop(self):
        pass

    async def _plural(self, item_id: str) -> str:
        item = await self._catalog.get_item(item_id)
        return item["plural"]

    async def get_one(
        self, item_id: str, id: str, draft: str, params: Optional[dict] = None, subject: Optional[dict] = None
    ) -> dict:
        plural = await self._plural(item_id)
        response = await self._transport.request("GET", f"/drafts/{plural}/{id}/{draft}", params=params)
        return decode_envelope(response)["data"]

    async def get_many(
        self, item_id: str, draft: str, params: Optional[dict] = None, subject: Optional[dict] = None
    ) -> dict:
        plural = await self._plural(item_id)
        response = await self._transport.request("GET", f"/drafts/{plural}/{draft}", params=params)
        envelope = decode_envelope(response)
        return {"items": envelope["data"], "total": envelope["meta"].get("size", len(envelope["data"]))}

    async def save(self, item_id: str, id: str, draft: str, fields: dict, subject: Optional[dict] = None) -> dict:
        plural = await self._plural(item_id)
        response = await self._transport.request("PUT", f"/drafts/{plural}/{id}/{draft}", body=fields)
        return decode_envelope(response)["data"]

    async def publish(self, item_id: str, id: str, draft: str, subject: Optional[dict] = None) -> dict:
        plural = await self._plural(item_id)
        response = await self._transport.request("POST", f"/drafts/{plural}/{id}/{draft}/publish")
        return decode_envelope(response)["data"]

    async def discard(self, item_id: str, id: str, draft: str, subject: Optional[dict] = None) -> None:
        plural = await self._plural(item_id)
        response = await self._transport.request("DELETE", f"/drafts/{plural}/{id}/{draft}")
        decode_envelope(response)
