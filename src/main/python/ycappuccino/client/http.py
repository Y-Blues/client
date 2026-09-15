"""
ApiClient: thin async HTTP client for the API exposed by ycappuccino-http-server
(https://.../http_server/README.md): envelope {"status", "meta", "data"}, routes
/api/crud/<plural>, /api/services/<name>.

Pure Python, no dependency on Pelix/iPOPO and no import-time dependency on pyodide: this module
imports only ycappuccino.api.endpoints_storage (import-clean, see
client/docs/superpowers/specs/2026-09-15-client-design.md §0) to reuse its exception family, so a
caller that already knows how to handle NotFound/Forbidden/... from a server-side use case handles
the same classes here. It is plain async Python, not a YCappuccinoComponent: no framework, no
Pelix, in the browser.

Method names and parameter order mirror ycappuccino.api.endpoints_storage.ICrud and
ycappuccino.api.endpoints_service.IServiceEndpoint, minus "subject" (the server derives it from
the HTTP headers, there is nothing to pass here).
"""

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from ycappuccino.api.endpoints_storage import (
    CrudError,
    Forbidden,
    InvalidRequest,
    NotAuthenticated,
    NotFound,
)

_ERROR_BY_STATUS = {
    401: NotAuthenticated,
    403: Forbidden,
    404: NotFound,
    400: InvalidRequest,
}


@dataclass
class RawResponse:
    """what a Transport returns: the raw HTTP response, before envelope decoding"""

    status: int
    headers: dict = field(default_factory=dict)
    body: bytes = b""


class ApiClient:
    """async HTTP client for /api/crud/<plural> and /api/services/<name>"""

    def __init__(self, base_url: str, transport=None, token: Optional[str] = None):
        self._base_url = base_url.rstrip("/")
        self._transport = transport
        self._token = token

    async def get_one(self, plural: str, id: str, params: Optional[dict] = None) -> dict:
        """document id; NotFound when missing"""
        return await self._request("GET", f"/api/crud/{plural}/{id}", params=params)

    async def get_many(self, plural: str, params: Optional[dict] = None) -> dict:
        """{"items": documents matching params, "total": number of matching documents}"""
        envelope = await self._request_envelope("GET", f"/api/crud/{plural}", params=params)
        return {"items": envelope["data"], "total": envelope["meta"].get("size", len(envelope["data"]))}

    async def create(self, plural: str, fields: dict) -> dict:
        """upsert fields["_id"], or a new uuid decided by the server, and return it"""
        return await self._request("POST", f"/api/crud/{plural}", json_body=fields)

    async def update(self, plural: str, id: str, fields: dict) -> dict:
        """upsert the fields of the document id and return it"""
        return await self._request("PUT", f"/api/crud/{plural}/{id}", json_body=fields)

    async def delete(self, plural: str, id: str) -> None:
        """delete the document id and its drafts; NotFound when missing"""
        await self._request("DELETE", f"/api/crud/{plural}/{id}")

    async def delete_many(self, plural: str, filter: dict) -> int:
        """delete the documents matching the non empty filter; return their number"""
        data = await self._request("DELETE", f"/api/crud/{plural}", params={"filter": filter})
        return data["deleted"]

    async def call(
        self,
        name: str,
        method: str = "POST",
        extra_path: Optional[list] = None,
        params: Optional[dict] = None,
        body: Any = None,
    ) -> Any:
        """call the named service; NotFound if the server has no service with this name"""
        path = "/api/services/" + "/".join([name, *(extra_path or [])])
        return await self._request(method, path, params=params, json_body=body)

    async def _request(self, method: str, path: str, params: Optional[dict] = None, json_body: Any = None) -> Any:
        envelope = await self._request_envelope(method, path, params=params, json_body=json_body)
        return envelope["data"]

    async def _request_envelope(
        self, method: str, path: str, params: Optional[dict] = None, json_body: Any = None
    ) -> dict:
        url = self._base_url + path
        query = _encode_query(params)
        if query:
            url = f"{url}?{query}"
        headers = {}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        body = None
        if json_body is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(json_body).encode()
        transport = self._transport or _default_transport()
        response = await transport(method, url, headers, body)
        envelope = json.loads(response.body) if response.body else {"status": response.status, "meta": {}, "data": None}
        if response.status >= 400:
            message = envelope.get("data", {}).get("error", f"HTTP {response.status}")
            raise _ERROR_BY_STATUS.get(response.status, CrudError)(message)
        return envelope


def _encode_query(params: Optional[dict]) -> str:
    """dict/list values are sent as JSON text (what storage's Manager expects from an HTTP client,
    see storage/README.md); scalars are sent as-is; None values are omitted."""
    if not params:
        return ""
    from urllib.parse import urlencode

    encoded = {}
    for key, value in params.items():
        if value is None:
            continue
        encoded[key] = json.dumps(value) if isinstance(value, (dict, list)) else value
    return urlencode(encoded)


def _default_transport():
    from ycappuccino.client.pyodide_transport import pyodide_transport

    return pyodide_transport
