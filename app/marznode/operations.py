import logging
from collections import defaultdict
from typing import TYPE_CHECKING

from app.marznode.registry import node_registry
from app.utils.async_utils import fire_and_forget
from ..models.user import User

logger = logging.getLogger(__name__)

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
        node = node_registry.get(node_id)
        if node:
            fire_and_forget(
                node.update_user(
                    user=User.model_validate(user),
                    inbounds=tags,
                    device_limit=user.device_limit,
                    allowed_fingerprints=allowed_fingerprints,
                )
            )


async def _resync_node(node_id: int, node) -> None:
    try:
        await node.resync_users()
    except Exception as exc:  # noqa: BLE001 - diagnostics only
        logger.warning(
            "node %d: bulk resync failed (%s: %s); the node keeps its "
            "current user set until the next reconnect",
            node_id,
            type(exc).__name__,
            exc,
        )


def resync_nodes(node_ids) -> None:
    """Reconcile the complete user list on each of ``node_ids``.

    One ``RepopulateUsers`` call per node instead of one ``SyncUsers``
    message per user per node. Used by the bulk paths -- editing or
    deleting a service changes access for every user holding it -- where
    the per-user fan-out costs a database round trip per user and, on the
    node side, arrives as thousands of stream messages. ``RepopulateUsers``
    is what the reconnect path already sends, and marznode diffs it against
    its own storage, so users whose access did not change cost nothing.
    """
    for node_id in set(node_ids):
        node = node_registry.get(node_id)
        if node:
            fire_and_forget(_resync_node(node_id, node))


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
    except Exception as e:
        logger.warning("Failed to get fingerprints for user %d: %s", user_id, e)
        return []


def remove_user_from_nodes(user: "DBUser"):
    node_ids = set(inb.node_id for inb in user.inbounds)

    for node_id in node_ids:
        node = node_registry.get(node_id)
        if node:
            fire_and_forget(
                node.update_user(user=user, inbounds=[])
            )


async def remove_node(node_id: int):
    await node_registry.unregister(node_id)


async def add_node(db_node, certificate):
    from app.services.node_service import add_node as _add

    await _add(db_node, certificate)


__all__ = [
    "update_user",
    "remove_user_from_nodes",
    "resync_nodes",
    "add_node",
    "remove_node",
]
