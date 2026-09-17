"""
FALLBACK_INTERFACES: the backend interfaces the client proxies when it could not ask the backend what it
provides (discovery.py): the storage and service use cases every ycappuccino backend with http_server
exposes. When discovery works, the client proxies exactly the public interfaces the backend reports.
"""

from ycappuccino.api.endpoints_service import IServiceEndpoint
from ycappuccino.api.endpoints_storage import ICrud, IDrafts, IItemCatalog

FALLBACK_INTERFACES = (ICrud, IDrafts, IItemCatalog, IServiceEndpoint)


def qualified_path(interface: type) -> str:
    return f"{interface.__module__}.{interface.__qualname__}"
