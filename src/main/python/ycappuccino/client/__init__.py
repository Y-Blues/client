"""
YCappuccino pyscript client: real ICrud/IDrafts/IItemCatalog/IServiceEndpoint implementations
(RemoteCrud/RemoteDrafts/RemoteItemCatalog/RemoteServiceEndpoint), backed by HTTP/fetch, meant to
run under a real ycappuccino.core.framework.Framework in the browser (Pyodide) - auto-discovered
the moment bundle_prefix includes "ycappuccino.client", exactly like any other provider package in
this ecosystem. App code never imports this package directly: it depends on the api interfaces,
the same way server-side code does. See client/README.md.
"""
