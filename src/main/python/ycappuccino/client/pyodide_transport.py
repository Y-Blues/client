"""
pyodide_transport: the fetch HttpTransport uses when no IHttpFetcher is published (the real
deployment case: a browser page, running under Pyodide).

Verified in Chromium with Pyodide 0.28.3 (2026-09-17, see README): discovery, login and authenticated
calls go through this function. Not verified in Firefox or Safari.

pyodide.http is imported here, inside the function, never at module import time: this keeps
ycappuccino.client.transport importable (and unit-testable) in plain CPython, where pyodide does
not exist. The ImportError is turned into an explicit RuntimeError instead of leaking a bare
ModuleNotFoundError with no context.

credentials="same-origin": sends the browser's own cookies (if any) alongside the Authorization
header HttpTransport already attaches - harmless when there is none, and lets a server that also
issues a session cookie (see permissions_app/README.md's `login_cookie` service) work without
extra plumbing. It does NOT mean this module reads Set-Cookie: browser fetch() implementations do
not expose Set-Cookie to JavaScript/Pyodide by spec, which is exactly why HttpTransport's token
comes from the JSON body of a login service call (`{"token": ...}`, see permissions_app's
`login` service), never from a response header - NOT verified here, but a documented consequence
of the fetch spec, not a Pyodide-specific guess.
"""

from ycappuccino.client.transport import RawResponse


async def pyodide_transport(method: str, url: str, headers: dict, body: bytes | None) -> RawResponse:
    try:
        from pyodide.http import pyfetch
    except ImportError as error:
        raise RuntimeError(
            "no transport available: ycappuccino.client.pyodide_transport.pyodide_transport "
            "requires pyodide.http, which is only present when running under Pyodide in a "
            "browser. Publish a fake ycappuccino.client.transport.IHttpFetcher component (or "
            "inject one directly into HttpTransport) when running outside Pyodide, e.g. in tests."
        ) from error

    response = await pyfetch(url, method=method, headers=headers, body=body, credentials="same-origin")
    payload = await response.bytes()
    return RawResponse(status=response.status, headers={}, body=bytes(payload))
