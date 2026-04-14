"""Marznode communication layer.

``node_registry`` is the single source of truth for active node connections.
Legacy code may still reference ``nodes`` (a dict-like proxy) for backward
compat — prefer ``node_registry`` in new code.
"""

from . import operations
from .base import MarzNodeBase
from .grpcio import MarzNodeGRPCIO
from .grpclib import MarzNodeGRPCLIB
from .registry import node_registry

nodes = node_registry._nodes

__all__ = [
    "node_registry",
    "nodes",
    "operations",
    "MarzNodeGRPCIO",
    "MarzNodeGRPCLIB",
    "MarzNodeBase",
]
