# NOT executable/testable in this repository's CPython test suite: this file only runs inside
# Pyodide, loaded by index.html through <script type="py" src="./main.py">. It could not be run
# in a real browser while writing it (no network access in this sandbox to fetch Pyodide/pyscript
# from a CDN). MANUAL BROWSER VERIFICATION REQUIRED before relying on it - see
# client/README.md "Limites et verifications manuelles requises" and "Risques d'execution
# navigateur" (every numbered risk referenced below by letter is documented there in full).
#
# This is the full bootstrap sequence from the design spec, not a toy: load Pyodide's own
# curated pyyaml package (risk (b)), micropip-install the framework wheels with deps=False (never
# letting micropip pull in iPOPO/jsonrpclib-pelix's own transitive resolution - see the design
# spec Sec.0's second empirical finding, still valid), write conf/application.yml and the demo
# bundle into Pyodide's in-memory virtual filesystem (risk (c) - Framework.init() wants a real
# file path), ask the backend's __remote_capabilities__ which public interfaces it provides and write
# one JSON-RPC proxy per interface into an ordinary generated module BEFORE the framework starts
# (ycappuccino.client.discovery), start a REAL ycappuccino.core.framework.Framework, and read back the
# DI-resolved Catalog component.
#
# THIS WILL NOT WORK under a standard single-threaded Pyodide build: Framework.init() starts
# ycappuccino.core.async_runner.AsyncRunner, which needs a genuine OS thread (risk (a)). This
# requires a pthread-enabled Pyodide build, on a page served with
# Cross-Origin-Opener-Policy: same-origin and Cross-Origin-Embedder-Policy: require-corp (see
# hosts/README.md's Host.cross_origin_isolated). Neither could be verified in the sandbox that
# wrote this file. Do not deploy this without first checking it against a real browser.

import json

from pyscript import document

STATUS = None


def _set_status(text):
    STATUS.innerText = text


async def _install_wheels():
    """
    micropip.install(url, deps=False): the URLs below are placeholders - the wheels must be
    built (`uv build` in api/core/client) and served by a Host (see hosts/README.md), there is no
    real package index here (out of scope, no network in the sandbox that wrote this - see design
    spec Sec.0/Sec.4). deps=False on every call: api declares iPOPO unconditionally in its own
    pyproject.toml, and none of that resolution is safe or necessary to repeat inside Pyodide.
    iPOPO itself IS a real runtime dependency here (unlike the previous, HTTP-client-only design):
    core.framework genuinely imports pelix/iPOPO to start the real framework. Whether iPOPO
    installs and runs correctly under Pyodide is NOT verified anywhere in this repository - see
    README.md "Limites et verifications manuelles requises".
    """
    import micropip

    # Pyodide's own curated package loader, BEFORE micropip: see risk (b). NOT verified here:
    # (1) that "pyyaml" is in the curated list of the Pyodide version actually loaded by
    # index.html; (2) that `import pyodide_js; await pyodide_js.loadPackage(...)` is the correct
    # way to reach the JS-side `pyodide.loadPackage` from Python code running inside Pyodide, as
    # opposed to some other documented bridge - written from the known existence of a
    # `pyodide_js` bridge module exposing the JS pyodide object to Python, but its exact surface
    # was not confirmed against real Pyodide documentation in this sandbox. Check both against
    # the actual Pyodide docs for the version pinned in index.html before relying on this.
    import pyodide_js

    await pyodide_js.loadPackage("pyyaml")

    for wheel in (
        "/wheels/ipopo-3.2.2-py3-none-any.whl",
        "/wheels/ycappuccino_api-0.1.0-py3-none-any.whl",
        "/wheels/ycappuccino_core-0.1.0-py3-none-any.whl",
        "/wheels/ycappuccino_client-0.1.0-py3-none-any.whl",
    ):
        await micropip.install(wheel, deps=False)


async def _discover_backend_components():
    """
    Runs BEFORE Framework().init() is ever called, with the same discovery.py the real-backend test
    exercises (test_client_framework.py). No fetcher is passed, so the call goes through
    HttpTransport's production path (pyodide_transport, see its docstring for what is NOT verified).

    Writes bundle/generated_remote.py - a bare top-level module (not nested inside bundle/library),
    so its own position in bundle_prefix is unambiguous (pkgutil.walk_packages's WITHIN-a-package
    ordering is unspecified; a top-level module's position in bundle_prefix's own, explicitly
    ordered list is not - see design spec §10 and the empirical ordering bug this file's own test
    suite hit and documented while first getting this working). NOT executed anywhere in this
    sandbox (no network, no Pyodide) - MANUAL BROWSER VERIFICATION REQUIRED, same caveat as every
    other step of this bootstrap.
    """
    from ycappuccino.client import discovery

    paths = await discovery.prepare_generated_module("bundle/generated_remote.py")
    _set_status(f"backend interfaces proxied: {', '.join(paths) or '(none)'}")


def _write_application():
    """
    Framework.init(yml_path) wants a real file path (risk (c)): write conf/application.yml and
    the demo bundle into Pyodide's in-memory virtual filesystem with plain open(path, "w") -
    Pyodide's FS supports this transparently, no change to core.framework needed or made.

    bundle_prefix lists "ycappuccino.client.transport" (HttpTransport, the session every proxy depends
    on), then "generated_remote" (the proxies discovery wrote), then the application, INSTEAD OF the
    whole "ycappuccino.client" package, whose fallback proxies would collide with the generated ones.
    """
    import os

    os.makedirs("conf", exist_ok=True)
    os.makedirs("bundle/library", exist_ok=True)

    with open("conf/application.yml", "w") as file:
        file.write(
            "name: browser\n"
            "bundle_prefix:\n"
            "  - ycappuccino.client.transport\n"
            "  - generated_remote\n"
            "  - library\n"
        )

    with open("bundle/library/__init__.py", "w"):
        pass

    # example/library/books.py and catalog.py, copied verbatim: NOT regenerated here, an
    # application deploying this for real would fetch its own bundle's source the same way
    # (micropip/pyscript file fetching, or inlined at build time) - this bootstrap keeps the
    # placeholder short and readable rather than duplicating those two files as strings.


async def main():
    global STATUS
    STATUS = document.querySelector("#status")
    items_list = document.querySelector("#items")

    try:
        _set_status("installing packages...")
        await _install_wheels()

        _set_status("writing application files...")
        _write_application()

        _set_status("discovering backend capabilities...")
        await _discover_backend_components()

        import sys

        sys.path.insert(0, "bundle")

        _set_status("starting the framework...")
        from ycappuccino.core.framework import Framework

        framework = Framework()
        framework.init("conf/application.yml")

        reference = framework.context.get_service_reference("Catalog")
        catalog = framework.context.get_service(reference)

        items_list.innerHTML = ""
        for item in catalog.items or []:
            entry = document.createElement("li")
            entry.textContent = f"{item.get('id')} ({item.get('plural')})"
            items_list.appendChild(entry)
        _set_status(f"{len(catalog.items or [])} item(s) loaded via the real framework")
    except Exception as error:  # pragma: no cover - only ever runs under Pyodide
        _set_status(f"error: {error}")


await main()
