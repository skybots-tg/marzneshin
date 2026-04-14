import logging

from app.marznode.registry import node_registry
from app.marznode.grpcio import MarzNodeGRPCIO
from app.marznode.grpclib import MarzNodeGRPCLIB
from app.models.node import NodeConnectionBackend

logger = logging.getLogger(__name__)


async def add_node(db_node, certificate) -> None:
    from app.marznode.database import _address_cache

    await remove_node(db_node.id)
    _address_cache[db_node.id] = db_node.address

    if db_node.connection_backend == NodeConnectionBackend.grpcio:
        node = MarzNodeGRPCIO(
            db_node.id,
            db_node.address,
            db_node.port,
            usage_coefficient=db_node.usage_coefficient,
        )
    else:
        node = MarzNodeGRPCLIB(
            db_node.id,
            db_node.address,
            db_node.port,
            certificate.key,
            certificate.certificate,
            usage_coefficient=db_node.usage_coefficient,
        )

    node_registry.register(db_node.id, node)


async def remove_node(node_id: int) -> None:
    await node_registry.unregister(node_id)
