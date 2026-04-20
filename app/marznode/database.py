import asyncio
import logging
import threading

from app.db import crud, GetDB, device_crud
from app.models.node import NodeStatus

logger = logging.getLogger(__name__)

_address_cache: dict[int, str] = {}

_MAX_NODE_DB_OPS = 10
_node_db_sem = threading.BoundedSemaphore(_MAX_NODE_DB_OPS)
_node_db_waiting = 0
_node_db_waiting_lock = threading.Lock()


def _acquire_node_db(timeout: float = 60) -> bool:
    global _node_db_waiting
    with _node_db_waiting_lock:
        _node_db_waiting += 1
    try:
        acquired = _node_db_sem.acquire(timeout=timeout)
        if not acquired:
            logger.error(
                "Node DB semaphore acquire timed out after %.0fs "
                "(%d waiters). Possible deadlock or very slow queries.",
                timeout,
                _node_db_waiting,
            )
        return acquired
    finally:
        with _node_db_waiting_lock:
            _node_db_waiting -= 1


def _release_node_db():
    _node_db_sem.release()


def get_node_db_pressure() -> dict:
    return {
        "max_concurrent": _MAX_NODE_DB_OPS,
        "waiting": _node_db_waiting,
    }


class MarzNodeDB:
    def list_users(self):
        if not _acquire_node_db():
            logger.error(
                "Node %d: skipping list_users, semaphore timeout", self.id
            )
            return []

        try:
            with GetDB() as db:
                users = crud.get_node_users(db, self.id)
                if users:
                    user_ids = [u["id"] for u in users]
                    devices_by_user = device_crud.get_devices_for_users_batch(
                        db, user_ids, is_blocked=False
                    )
                    if devices_by_user:
                        users_by_id = {u["id"]: u for u in users}
                        for uid, devices in devices_by_user.items():
                            target = users_by_id.get(uid)
                            if target is not None:
                                target["allowed_fingerprints"] = [
                                    d.fingerprint for d in devices
                                ]
        finally:
            _release_node_db()

        return users

    def store_backends(self, backends):
        if not _acquire_node_db():
            logger.error(
                "Node %d: skipping store_backends, semaphore timeout", self.id
            )
            return

        try:
            inbounds = [
                inbound
                for backend in backends
                for inbound in backend.inbounds
            ]
            with GetDB() as db:
                crud.ensure_node_backends(db, backends, self.id)
                crud.ensure_node_inbounds(db, inbounds, self.id)
        finally:
            _release_node_db()

    def set_status(self, status: NodeStatus, message: str | None = None):
        if not _acquire_node_db():
            logger.error(
                "Node %d: skipping set_status, semaphore timeout", self.id
            )
            return

        try:
            with GetDB() as db:
                crud.update_node_status(db, self.id, status, message)
        finally:
            _release_node_db()

    async def _set_unhealthy(self, message: str | None = None):
        await asyncio.to_thread(
            self.set_status, NodeStatus.unhealthy, message
        )

        from app.notification.node_alerts import notify_node_unhealthy

        address = _address_cache.get(self.id, "unknown")
        await notify_node_unhealthy(self.id, address, message)
