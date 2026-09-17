"""
HttpTransport: the single native component every generated proxy (rpc_proxy.py) depends on to reach the
backend, and the client's ISession. It owns:

- the base URL ("/api" by default: the client is served by the backend it calls, through a Host),
  overridable through IConfiguration under "client.base_url", read once at start();
- the current bearer token (set_token/get_token/clear_token), sent with every call;
- turning a call into an HTTP request and its {"status", "meta", "data"} envelope back into a result or
  the matching endpoints_storage error (decode_envelope); dispatch() is the JSON-RPC call proxies use.

The low-level fetch goes to an IHttpFetcher when one is given (unit tests), otherwise to
ycappuccino.client.pyodide_transport.pyodide_transport, the only place importing pyodide.
"""

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urlencode

from ycappuccino.api.core import IConfiguration
from ycappuccino.api.core_base import YCappuccinoComponent
from ycappuccino.api.endpoints_storage import (
    CrudError,
    Forbidden,
    InvalidRequest,
    NotAuthenticated,
    NotFound,
)

DEFAULT_BASE_URL = "/api"
_CONFIG_KEY = "client.base_url"

_ERROR_BY_STATUS = {
    401: NotAuthenticated,
    403: Forbidden,
    404: NotFound,
    400: InvalidRequest,
}


@dataclass
class RawResponse:
    """what an IHttpFetcher returns: the raw HTTP response, before envelope decoding"""

    status: int
    headers: dict = field(default_factory=dict)
    body: bytes = b""


class IHttpFetcher(YCappuccinoComponent, ABC):
    """
    low-level HTTP transport used by HttpTransport when one is published. Not required: with
    none published, HttpTransport falls back to pyodide_transport.pyodide_transport.

    KNOWN FRAGILITY, discovered while writing the framework test, not a hypothetical: this
    is an Optional[IHttpFetcher] dependency, and HttpTransport lives in the "ycappuccino.*"
    namespace package. Publishing a fake IHttpFetcher from a temporary test package listed
    BEFORE ycappuccino.client in bundle_prefix (the pattern this docstring used to recommend)
    was found, by direct instrumentation, to leave HttpTransport's fetcher permanently None even
    though the fake service was independently confirmed present and discoverable in the Pelix
    registry at HttpTransport's own construction time. This reproduces the EXACT same quirk
    hosts/src/main/python/ycappuccino/hosts/servlet.py's own docstring already documents: "an
    optional dependency satisfied elsewhere in the same multi-path 'ycappuccino.*' namespace
    package was observed to resolve non-deterministically (sometimes None) depending on scan
    timing". hosts' fix (make the dependency mandatory) is not available here (HttpTransport
    must default to no fetcher in real deployments). Confirmed NOT to reproduce when the
    provider and consumer are both plain, non-namespace-package modules, or both live in the
    SAME temporary test package - only the cross-("ycappuccino" namespace package)-boundary case
    fails. Net effect: publishing a real IHttpFetcher component from an application package is
    NOT proven reliable by anything in this repository, and test_client_framework.py does NOT
    use this mechanism (it replaces ycappuccino.client.pyodide_transport.pyodide_transport
    directly instead). IHttpFetcher is kept as a documented
    extension point and is still exercised safely by test_transport.py, entirely in-process
    (HttpTransport constructed directly, no Pelix involved) where this quirk cannot occur.
    """

    @abstractmethod
    async def fetch(self, method: str, url: str, headers: dict, body: Optional[bytes]) -> RawResponse:
        """perform the request and return the raw response; let network errors propagate
        unwrapped, exactly like remote/call.py and http_server's own generic-500 handling do"""


class ISession(YCappuccinoComponent, ABC):
    """
    the signed-in state of this client: the only client-specific service application code may depend
    on. Once ILoginService.login() returned a token, set_token() makes every later backend call carry
    it; the backend derives the caller's subject from it, the client never sends a subject itself.
    """

    @abstractmethod
    def set_token(self, token: Optional[str]) -> None:
        """the token sent with every later call, None to call anonymously"""

    @abstractmethod
    def get_token(self) -> Optional[str]:
        """the current token, or None"""

    @abstractmethod
    def clear_token(self) -> None:
        """call anonymously from now on"""


DISPATCH_PATH = "/services/__remote_dispatch__"


class HttpTransport(ISession):
    """same-origin HTTP transport shared by every generated proxy, and the client's session"""

    def __init__(
        self,
        configuration: Optional[IConfiguration] = None,
        fetcher: Optional[IHttpFetcher] = None,
    ) -> None:
        self._configuration = configuration
        self._fetcher = fetcher
        self._base_url = DEFAULT_BASE_URL
        self._token: Optional[str] = None

    async def start(self) -> None:
        if self._configuration is not None:
            self._base_url = self._configuration.get(_CONFIG_KEY, DEFAULT_BASE_URL)

    async def stop(self) -> None:
        pass

    # ------------------------------------------------------------------ token (session state)

    def set_token(self, token: Optional[str]) -> None:
        self._token = token

    def get_token(self) -> Optional[str]:
        return self._token

    def clear_token(self) -> None:
        self._token = None

    # ------------------------------------------------------------------ requests

    async def request(
        self, method: str, path: str, params: Optional[dict] = None, body: Any = None
    ) -> RawResponse:
        """
        path is relative to the base URL (e.g. "/crud/books/dune", never "/api/crud/..."):
        HttpTransport owns the base URL, proxies never hardcode "/api".
        """
        url = self._base_url.rstrip("/") + path
        query = _encode_query(params)
        if query:
            url = f"{url}?{query}"

        headers = {}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        encoded_body = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            encoded_body = json.dumps(body).encode()

        if self._fetcher is not None:
            return await self._fetcher.fetch(method, url, headers, encoded_body)

        from ycappuccino.client.pyodide_transport import pyodide_transport

        return await pyodide_transport(method, url, headers, encoded_body)


    async def dispatch(self, qualified_path: str, method_name: str, kwargs: dict) -> Any:
        """one JSON-RPC call to `method_name` of the backend specification `qualified_path`, through
        its __remote_dispatch__ service; returns the method's result, or raises the error the backend
        answered (NotAuthenticated, Forbidden, NotFound, InvalidRequest, CrudError)"""
        response = await self.request("POST", f"{DISPATCH_PATH}/{qualified_path}/{method_name}", body={"kwargs": kwargs})
        return decode_envelope(response)["data"]["result"]


def decode_envelope(response: RawResponse) -> dict:
    """
    decode the {"status", "meta", "data"} envelope (http_server/README.md) a proxy
    got back from HttpTransport.request(), or raise the endpoints_storage error matching its HTTP
    status - adapted from remote/call.py's _translate() (not imported: client does not depend on
    remote).
    """
    if response.body:
        envelope = json.loads(response.body)
    else:
        envelope = {"status": response.status, "meta": {}, "data": None}

    if response.status >= 400:
        data = envelope.get("data")
        message = data.get("error", f"HTTP {response.status}") if isinstance(data, dict) else f"HTTP {response.status}"
        raise _ERROR_BY_STATUS.get(response.status, CrudError)(message)

    return envelope


def _encode_query(params: Optional[dict]) -> str:
    """dict/list values are sent as JSON text (what storage's Manager expects from an HTTP
    client, see storage/README.md), scalars as-is, None values omitted"""
    if not params:
        return ""
    encoded = {}
    for key, value in params.items():
        if value is None:
            continue
        encoded[key] = json.dumps(value) if isinstance(value, (dict, list)) else value
    return urlencode(encoded)
