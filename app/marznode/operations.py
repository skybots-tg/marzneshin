import asyncio
from collections import defaultdict
from typing import TYPE_CHECKING

from app import marznode
from .grpcio import MarzNodeGRPCIO
from .grpclib import MarzNodeGRPCLIB
from ..models.node import NodeConnectionBackend
from ..models.user import User

if TYPE_CHECKING:
    from sqlalchemy.orm import Session as _Session
    from app.db import User as DBUser


def update_user(
    user: "DBUser", old_inbounds: set | None = None, remove: bool = False,
    db: "_Session | None" = None,
):
    """updates a user on all related nodes"""
    if old_inbounds is None:
        old_inbounds = set()

    node_inbounds = defaultdict(list)
    if remove:
        for inb in user.inbounds:
            node_inbounds[inb.node_id]
    else:
        for inb in user.inbounds:
            node = marznode.nodes.get(inb.node_id)
            if user.data_limit_reached and node and node.usage_coefficient > 0:
                node_inbounds[inb.node_id]
            else:
                node_inbounds[inb.node_id].append(inb.tag)

    for inb in old_inbounds:
        node_inbounds[inb[0]]

    allowed_fingerprints = _get_allowed_fingerprints(user.id, db=db)

    for node_id, tags in node_inbounds.items():
        if marznode.nodes.get(node_id):
            asyncio.ensure_future(
                marznode.nodes[node_id].update_user(
                    user=User.model_validate(user), 
                    inbounds=tags,
                    device_limit=user.device_limit,
                    allowed_fingerprints=allowed_fingerprints,
                )
            )


def _get_allowed_fingerprints(user_id: int, db=None) -> list[str]:
    """Get list of allowed device fingerprints for user.
    Reuses the caller's session when provided to avoid nested pool checkouts.
    """
    from app.db import device_crud

    if db is not None:
        devices = device_crud.get_user_devices(
            db, user_id, is_blocked=False, limit=1000
        )
        return [d.fingerprint for d in devices]

    from app.db import GetDB
    try:
        with GetDB() as db:
            devices = device_crud.get_user_devices(
                db, user_id, is_blocked=False, limit=1000
            )
            return [d.fingerprint for d in devices]
    except Exception:
        return []


async def remove_user(user: "DBUser"):
    node_ids = set(inb.node_id for inb in user.inbounds)

    for node_id in node_ids:
        if marznode.nodes.get(node_id):
            asyncio.ensure_future(
                marznode.nodes[node_id].update_user(user=user, inbounds=[])
            )


async def remove_node(node_id: int):
    if node_id in marznode.nodes:
        await marznode.nodes[node_id].stop()
        del marznode.nodes[node_id]


async def add_node(db_node, certificate):
    await remove_node(db_node.id)
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
    marznode.nodes[db_node.id] = node


__all__ = ["update_user", "add_node", "remove_node"]
