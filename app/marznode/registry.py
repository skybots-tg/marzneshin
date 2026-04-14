import logging
import threading
from typing import Optional

from .base import MarzNodeBase

logger = logging.getLogger(__name__)


class NodeRegistry:
    """Thread-safe registry of active Marznode connections."""

    def __init__(self):
        self._nodes: dict[int, MarzNodeBase] = {}
        self._lock = threading.Lock()

    def get(self, node_id: int) -> Optional[MarzNodeBase]:
        with self._lock:
            return self._nodes.get(node_id)

    def register(self, node_id: int, node: MarzNodeBase) -> None:
        with self._lock:
            self._nodes[node_id] = node
        logger.debug("Node %d registered", node_id)

    async def unregister(self, node_id: int) -> None:
        with self._lock:
            node = self._nodes.pop(node_id, None)
        if node:
            await node.stop()
            logger.debug("Node %d unregistered and stopped", node_id)

    def list_ids(self) -> list[int]:
        with self._lock:
            return list(self._nodes.keys())

    def items(self) -> list[tuple[int, MarzNodeBase]]:
        with self._lock:
            return list(self._nodes.items())

    def __contains__(self, node_id: int) -> bool:
        with self._lock:
            return node_id in self._nodes

    def __len__(self) -> int:
        with self._lock:
            return len(self._nodes)


node_registry = NodeRegistry()
