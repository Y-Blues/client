"""
RemoteServiceEndpoint: browser-side IServiceEndpoint, translating a call to
/api/services/<name>[/<extra_path>...] (http_server/README.md, endpoints_service/README.md).

No item_id/plural resolution needed here (services are named directly, not routed through the
item catalog); no subject to forward either, for the same reason as RemoteCrud/RemoteDrafts (see
remote_crud.py's docstring) - the bearer token on HttpTransport is what authenticates the call,
the server derives its own subject from it.

This is what a login flow uses: `await endpoint.call("login", "POST", [], {}, {"login": ...,
"password": ...}, None)` (mirroring permissions_app's LoginService, POST /api/services/login ->
{"token": ...}) returns a ServiceResult whose body holds the token; the caller then does
`transport.set_token(result.body["token"])` (transport: HttpTransport, itself injectable). Not
wired up automatically here on purpose: deciding *when* to log in, and what to do with the token
afterwards, is an application concern, not this component's.
"""

from typing import Any, Optional

from ycappuccino.api.endpoints_service import IServiceEndpoint, ServiceResult
from ycappuccino.client.transport import HttpTransport, decode_envelope


class RemoteServiceEndpoint(IServiceEndpoint):

    def __init__(self, transport: HttpTransport):
        self._transport = transport

    async def start(self):
        pass

    async def stop(self):
        pass

    async def call(
        self, name: str, method: str, extra_path: list, params: dict, body: Any, subject: Optional[dict]
    ) -> ServiceResult:
        path = "/services/" + "/".join([name, *(extra_path or [])])
        response = await self._transport.request(method, path, params=params, body=body)
        envelope = decode_envelope(response)
        return ServiceResult(body=envelope["data"])
