"""
The fallback proxies (known_interfaces.FALLBACK_INTERFACES), assigned at module level so the
framework's bundle_prefix scan installs them like hand-written components when bundle_prefix lists
"ycappuccino.client". A bootstrap that ran discovery (discovery.prepare_generated_module) lists its
generated module and "ycappuccino.client.transport" instead, never both.
"""

from ycappuccino.client.known_interfaces import FALLBACK_INTERFACES, qualified_path
from ycappuccino.client.rpc_proxy import make_rpc_proxy, remote_class_name

for _interface in FALLBACK_INTERFACES:
    globals()[remote_class_name(_interface)] = make_rpc_proxy(_interface, qualified_path(_interface))
del _interface
