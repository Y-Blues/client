"""
HttpTransport: the single native component all Remote* components (RemoteCrud, RemoteDrafts,
RemoteItemCatalog, RemoteServiceEndpoint) depend on to reach the real ycappuccino-http_server
backend over HTTP. It owns:

- the base URL ("/api" by default, same-origin: the client is served by the same backend it
  calls, via a Host - see hosts/README.md), overridable through IConfiguration under the key
  "client.base_url" (read once, at start() - same "no hot reload" convention as scheduler/hosts);
- the current bearer token, in memory (set_token/get_token/clear_token) - see the design spec
  (2026-09-15-client-design.md A.2) for why this lives here rather than in a separate
  "BrowserSession" component: there is exactly one transport, so there is exactly one place that
  needs the token, and splitting it into two components would only add a wiring hop for no
  behavioural gain. A login flow (calling IServiceEndpoint.call("login", ...), see
  permissions_app/README.md's "Connexion") reads the token out of the response body and calls
  set_token() on this component;
- turning a (method, path, params, body) call into a real HTTP request and back into a decoded
  envelope or a raised endpoints_storage error - decode_envelope() below, adapted from
  remote/call.py's _translate() (not imported: client must not depend on remote, and remote's
  peer-registry addressing model does not apply here - one fixed same-origin backend, not a set
  of named peers).

Low-level fetch is delegated to an IHttpFetcher, a YCappuccinoComponent-rooted interface defined
in this module (client is free to define its own component interfaces - describe_component()
in ycappuccino.core.component_factory treats any subclass of YCappuccinoComponent as an
injectable dependency type, not just the ones declared in ycappuccino.api). Production never
publishes one: HttpTransport then falls back to the lazily-imported
ycappuccino.client.pyodide_transport.pyodide_transport, the only place that ever imports
`pyodide` (inside a function, never at module level - see that module's docstring for what is
NOT verified about it in this sandbox).

Component-level unit tests (test_transport.py, test_remote_*.py) construct HttpTransport
directly with a hand-written IHttpFetcher, no framework involved at all (see core/README.md
"Tester ses composants") - this is safe and exercises IHttpFetcher for real. The real-framework
integration test (test_client_framework.py) does NOT publish an IHttpFetcher component, on
purpose: see IHttpFetcher's own docstring below for a real, discovered-not-hypothetical
namespace-package DI quirk that makes that mechanism unreliable specifically for
ycappuccino.client - it monkeypatches ycappuccino.client.pyodide_transport.pyodide_transport
directly instead.
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

    KNOWN FRAGILITY, discovered while writing test_client_framework.py, not a hypothetical: this
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
    use this mechanism (it monkeypatches ycappuccino.client.pyodide_transport.pyodide_transport
    directly instead - see that test's docstring). IHttpFetcher is kept as a documented
    extension point and is still exercised safely by test_transport.py, entirely in-process
    (HttpTransport constructed directly, no Pelix involved) where this quirk cannot occur.
    """

    @abstractmethod
    async def fetch(self, method: str, url: str, headers: dict, body: Optional[bytes]) -> RawResponse:
        """perform the request and return the raw response; let network errors propagate
        unwrapped, exactly like remote/call.py and http_server's own generic-500 handling do"""


class HttpTransport(YCappuccinoComponent):
    """same-origin HTTP transport shared by every Remote* component; see module docstring"""

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
        HttpTransport owns the base URL, Remote* components never hardcode "/api".
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


def decode_envelope(response: RawResponse) -> dict:
    """
    decode the {"status", "meta", "data"} envelope (http_server/README.md) a Remote* component
    got back from HttpTransport.request(), or raise the endpoints_storage error matching its HTTP
    status - adapted from remote/call.py's _translate(), generalized to CRUD (not just services)
    and without ServiceResult (RemoteServiceEndpoint builds that itself from the returned dict).
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
