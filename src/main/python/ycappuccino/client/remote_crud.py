"""
RemoteCrud: browser-side ICrud, translating every call to the /api/crud/<plural>... routes
http_server exposes (http_server/README.md), with the exact same authorization-driven error
family (NotFound/Forbidden/NotAuthenticated/InvalidRequest/CrudError) an application already
knows from server-side code - decode_envelope() (ycappuccino.client.transport) raises them from
the HTTP status, adapted from remote/call.py's _translate().

item_id -> plural: ICrud's methods take item_id (e.g. "book"), but http_server's routes are
plural-based (e.g. "/api/crud/books" - see ApiServlet._route_crud, which itself resolves the
other way with self._item_id(plural, subject) = (await catalog.get_item_by_plural(plural))["id"]).
RemoteCrud does the mirror lookup, item_id -> plural, via an injected IItemCatalog (in practice
the equally auto-discovered RemoteItemCatalog, see remote_item_catalog.py) rather than
hardcoding a naming convention: this is exactly the kind of cross-component wiring the real DI
container exists for, and it stays correct if the server's plural for an item is not simply
"item_id + s".

subject: kept as a parameter (mandatory, per ICrud's own signature) purely so app code type-checks
identically to server code and a function written to be reusable on both sides (take an ICrud,
call it the same way) compiles unchanged. Its value is silently ignored: the browser never holds
a decoded JWT to put in it (see design spec A.1 for the alternative considered - raising when
subject is not None - and why it was rejected: it would make exactly the kind of shared,
transport-agnostic app code this whole redesign exists to enable break specifically when deployed
to the browser, which defeats the point). Authentication is attached at the transport level
instead: HttpTransport.set_token() (see permissions_app's `login` service, called through
IServiceEndpoint, for how a token is obtained) puts a bearer token on every request; the SERVER
performs the actual authorization decision, using its own decoded subject, exactly as it does for
any other HTTP caller.
"""

from typing import Optional

from ycappuccino.api.endpoints_storage import ICrud, IItemCatalog
from ycappuccino.client.transport import HttpTransport, decode_envelope


class RemoteCrud(ICrud):

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
        self, item_id: str, id: str, params: Optional[dict] = None, subject: Optional[dict] = None
    ) -> dict:
        plural = await self._plural(item_id)
        response = await self._transport.request("GET", f"/crud/{plural}/{id}", params=params)
        return decode_envelope(response)["data"]

    async def get_many(self, item_id: str, params: Optional[dict] = None, subject: Optional[dict] = None) -> dict:
        plural = await self._plural(item_id)
        response = await self._transport.request("GET", f"/crud/{plural}", params=params)
        envelope = decode_envelope(response)
        return {"items": envelope["data"], "total": envelope["meta"].get("size", len(envelope["data"]))}

    async def create(self, item_id: str, fields: dict, subject: Optional[dict] = None) -> dict:
        plural = await self._plural(item_id)
        response = await self._transport.request("POST", f"/crud/{plural}", body=fields)
        return decode_envelope(response)["data"]

    async def update(self, item_id: str, id: str, fields: dict, subject: Optional[dict] = None) -> dict:
        plural = await self._plural(item_id)
        response = await self._transport.request("PUT", f"/crud/{plural}/{id}", body=fields)
        return decode_envelope(response)["data"]

    async def delete(self, item_id: str, id: str, subject: Optional[dict] = None) -> None:
        plural = await self._plural(item_id)
        response = await self._transport.request("DELETE", f"/crud/{plural}/{id}")
        decode_envelope(response)

    async def delete_many(self, item_id: str, filter: dict, subject: Optional[dict] = None) -> int:
        plural = await self._plural(item_id)
        response = await self._transport.request("DELETE", f"/crud/{plural}", params={"filter": filter})
        return decode_envelope(response)["data"]["deleted"]
