import logging

from app.marznode.registry import node_registry
from app.marznode.grpcio import MarzNodeGRPCIO
from app.marznode.grpclib import MarzNodeGRPCLIB
from app.models.node import NodeConnectionBackend

logger = logging.getLogger(__name__)


async def add_node(db_node, certificate, start_delay: float = 0.0) -> None:
    from app.marznode.database import _address_cache, _name_cache

    await remove_node(db_node.id)
    _address_cache[db_node.id] = db_node.address
    _name_cache[db_node.id] = db_node.name or ""

    if db_node.connection_backend == NodeConnectionBackend.grpcio:
        node = MarzNodeGRPCIO(
            db_node.id,
            db_node.address,
            db_node.port,
            usage_coefficient=db_node.usage_coefficient,
            start_delay=start_delay,
        )
    else:
        node = MarzNodeGRPCLIB(
            db_node.id,
            db_node.address,
            db_node.port,
            certificate.key,
            certificate.certificate,
            usage_coefficient=db_node.usage_coefficient,
            start_delay=start_delay,
        )

    node_registry.register(db_node.id, node)


async def remove_node(node_id: int) -> None:
    await node_registry.unregister(node_id)
