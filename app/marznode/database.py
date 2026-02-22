import logging

from app.db import crud, GetDB, device_crud
from app.models.node import NodeStatus

logger = logging.getLogger(__name__)


class MarzNodeDB:
    def list_users(self):
        with GetDB() as db:
            # Single query: returns (User.id, User.username, User.key, Inbound, User.device_limit)
            relations = crud.get_node_users(db, self.id)
            users = dict()
            for rel in relations:
                if not users.get(rel[0]):
                    users[rel[0]] = dict(
                        username=rel[1], 
                        id=rel[0], 
                        key=rel[2], 
                        inbounds=[],
                        device_limit=rel[4],  # device_limit from the query
                        allowed_fingerprints=[]
                    )
                users[rel[0]]["inbounds"].append(rel[3].tag)
            
            # Single batch query for all device fingerprints instead of N queries
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
        
        return list(users.values())

    def store_backends(self, backends):
        inbounds = [
            inbound for backend in backends for inbound in backend.inbounds
        ]
        with GetDB() as db:
            crud.ensure_node_backends(db, backends, self.id)
            crud.ensure_node_inbounds(db, inbounds, self.id)

    def set_status(self, status: NodeStatus, message: str | None = None):
        with GetDB() as db:
            crud.update_node_status(db, self.id, status, message)
