import asyncio
from collections import defaultdict
from typing import TYPE_CHECKING

from app.marznode.registry import node_registry
from ..models.node import NodeConnectionBackend
from ..models.user import User

if TYPE_CHECKING:
    from sqlalchemy.orm import Session as _Session
    from app.db.models.core import User as DBUser


def update_user(
    user: "DBUser",
    old_inbounds: set | None = None,
    remove: bool = False,
    db: "_Session | None" = None,
):
    """Updates a user on all related nodes."""
    if old_inbounds is None:
        old_inbounds = set()

    node_inbounds = defaultdict(list)
    if remove:
        for inb in user.inbounds:
            node_inbounds[inb.node_id]
    else:
        for inb in user.inbounds:
            node = node_registry.get(inb.node_id)
            if user.data_limit_reached and node and node.usage_coefficient > 0:
                node_inbounds[inb.node_id]
            else:
                node_inbounds[inb.node_id].append(inb.tag)

    for inb in old_inbounds:
        node_inbounds[inb[0]]

    allowed_fingerprints = _get_allowed_fingerprints(user.id, db=db)

    for node_id, tags in node_inbounds.items():
        if node_registry.get(node_id):
            asyncio.ensure_future(
                node_registry.get(node_id).update_user(
                    user=User.model_validate(user),
                    inbounds=tags,
                    device_limit=user.device_limit,
                    allowed_fingerprints=allowed_fingerprints,
                )
            )


def _get_allowed_fingerprints(user_id: int, db=None) -> list[str]:
    """Get list of allowed device fingerprints for user."""
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
        node = node_registry.get(node_id)
        if node:
            asyncio.ensure_future(
                node.update_user(user=user, inbounds=[])
            )


async def remove_node(node_id: int):
    await node_registry.unregister(node_id)


async def add_node(db_node, certificate):
    from app.services.node_service import add_node as _add

    await _add(db_node, certificate)


__all__ = ["update_user", "add_node", "remove_node"]
