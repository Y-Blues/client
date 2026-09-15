# NOT executable/testable in this repository's CPython test suite: this file only runs inside
# Pyodide, loaded by index.html through <script type="py" src="./main.py">. It could not be run
# in a real browser while writing it (no network access in this sandbox to fetch Pyodide/pyscript
# from the CDN). MANUAL BROWSER VERIFICATION REQUIRED before relying on it.
#
# Kept deliberately small and self-contained (no dependency on the ycappuccino-client wheel, no
# micropip.install here) so it stays "obviously correct by inspection", as asked: it only uses
# pyodide.http.pyfetch (documented Pyodide API) and pyscript.document (documented pyscript API for
# this CDN release), to fetch /api/items and render a trivial list in the DOM.
#
# A fuller client would install the shared code instead of hand-rolling a fetch here:
#
#   import micropip
#   # deps=False: see client/README.md "Ce qui est partage, et comment" - ycappuccino-api declares
#   # iPOPO as a dependency in its own pyproject.toml, which the client never needs at runtime.
#   await micropip.install("/wheels/ycappuccino_api-0.1.0-py3-none-any.whl", deps=False)
#   await micropip.install("/wheels/ycappuccino_client-0.1.0-py3-none-any.whl", deps=False)
#   from ycappuccino.client.http import ApiClient
#   client = ApiClient("")  # same-origin: relative to the page http_server/hosts are served from
#   items = await client.call  # etc., see README.md for the full ApiClient surface
#
# That part is commented out on purpose: it depends on wheels actually being built and served by
# a Host, which is out of scope here (see spec §0 and §4) and was never exercised.

import json

from pyodide.http import pyfetch
from pyscript import document


async def main():
    items_list = document.querySelector("#items")
    try:
        response = await pyfetch("/api/items")
        envelope = json.loads(await response.string())
        items = envelope["data"]
    except Exception as error:  # pragma: no cover - only ever runs under Pyodide
        items_list.innerHTML = f"<li>error fetching /api/items: {error}</li>"
        return

    if not items:
        items_list.innerHTML = "<li>no items</li>"
        return

    items_list.innerHTML = ""
    for item in items:
        entry = document.createElement("li")
        entry.textContent = f"{item.get('id')} ({item.get('plural')})"
        items_list.appendChild(entry)


await main()
