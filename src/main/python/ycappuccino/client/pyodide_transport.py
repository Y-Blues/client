"""
pyodide_transport: the Transport ApiClient uses by default, when none is injected.

NOT verified in this sandbox: there is no real Pyodide runtime available here (no network access
to fetch it, and this module is plain CPython). This function is written from the known Pyodide
API surface (pyodide.http.pyfetch, FetchResponse.status/.bytes()), but its exact behaviour -
fetch option names, header casing, credentials/CORS handling, and whether FetchResponse.bytes()
still exists under this shape in the Pyodide version actually loaded by static/index.html - is
NOT proven by anything in this repository. Manual verification in a real browser is required
before relying on this in production; see client/README.md.

pyodide.http is imported here, inside the function, never at module import time: this keeps
ycappuccino.client.http importable (and unit-testable) in plain CPython, where pyodide does not
exist. The ImportError is turned into an explicit RuntimeError instead of leaking a bare
ModuleNotFoundError with no context.
"""

from ycappuccino.client.http import RawResponse


async def pyodide_transport(method: str, url: str, headers: dict, body):
    try:
        from pyodide.http import pyfetch
    except ImportError as error:
        raise RuntimeError(
            "no transport available: ycappuccino.client.pyodide_transport.pyodide_transport "
            "requires pyodide.http, which is only present when running under Pyodide in a "
            "browser. Inject a Transport explicitly (e.g. a fake one for tests, or a different "
            "real one) when running outside Pyodide."
        ) from error

    response = await pyfetch(url, method=method, headers=headers, body=body, credentials="same-origin")
    payload = await response.bytes()
    return RawResponse(status=response.status, headers={}, body=bytes(payload))
