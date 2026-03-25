import logging
import threading
import time

from app.db import crud, GetDB, device_crud
from app.models.node import NodeStatus

logger = logging.getLogger(__name__)

# Throttle concurrent DB operations from node sync/status updates.
# Without this, a reconnection storm (all nodes reconnecting at once after
# a network blip) opens N×3+ DB connections simultaneously and exhausts the pool.
_MAX_NODE_DB_OPS = 10
_node_db_sem = threading.BoundedSemaphore(_MAX_NODE_DB_OPS)
_node_db_waiting = 0
_node_db_waiting_lock = threading.Lock()


def _acquire_node_db(timeout: float = 60) -> bool:
    """Acquire the node-DB semaphore; returns True on success."""
    global _node_db_waiting
    with _node_db_waiting_lock:
        _node_db_waiting += 1
    try:
        acquired = _node_db_sem.acquire(timeout=timeout)
        if not acquired:
            logger.error(
                "Node DB semaphore acquire timed out after %.0fs "
                "(%d waiters). Possible deadlock or very slow queries.",
                timeout, _node_db_waiting,
            )
        return acquired
    finally:
        with _node_db_waiting_lock:
            _node_db_waiting -= 1


def _release_node_db():
    _node_db_sem.release()


def get_node_db_pressure() -> dict:
    """Return current node-DB throttle stats (for monitoring)."""
    return {
        "max_concurrent": _MAX_NODE_DB_OPS,
        "waiting": _node_db_waiting,
    }


class MarzNodeDB:
    def list_users(self):
        if not _acquire_node_db():
            logger.error("Node %d: skipping list_users, semaphore timeout", self.id)
            return []

        try:
            with GetDB() as db:
                relations = crud.get_node_users(db, self.id)
                users = dict()
                for rel in relations:
                    if not users.get(rel[0]):
                        users[rel[0]] = dict(
                            username=rel[1],
                            id=rel[0],
                            key=rel[2],
                            inbounds=[],
                            device_limit=rel[4],
                            allowed_fingerprints=[],
                        )
                    users[rel[0]]["inbounds"].append(rel[3].tag)

                if users:
                    user_ids = list(users.keys())
                    devices_by_user = device_crud.get_devices_for_users_batch(
                        db, user_ids, is_blocked=False
                    )
                    for uid, devices in devices_by_user.items():
                        if uid in users:
                            users[uid]["allowed_fingerprints"] = [
                                d.fingerprint for d in devices
                            ]
        finally:
            _release_node_db()

        return list(users.values())

    def store_backends(self, backends):
        if not _acquire_node_db():
            logger.error("Node %d: skipping store_backends, semaphore timeout", self.id)
            return

        try:
            inbounds = [
                inbound for backend in backends for inbound in backend.inbounds
            ]
            with GetDB() as db:
                crud.ensure_node_backends(db, backends, self.id)
                crud.ensure_node_inbounds(db, inbounds, self.id)
        finally:
            _release_node_db()

    def set_status(self, status: NodeStatus, message: str | None = None):
        if not _acquire_node_db():
            logger.error("Node %d: skipping set_status, semaphore timeout", self.id)
            return

        try:
            with GetDB() as db:
                crud.update_node_status(db, self.id, status, message)
        finally:
            _release_node_db()
