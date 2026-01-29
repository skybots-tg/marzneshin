from app.db import crud, GetDB, device_crud
from app.models.node import NodeStatus


class MarzNodeDB:
    def list_users(self):
        with GetDB() as db:
            relations = crud.get_node_users(db, self.id)
            users = dict()
            for rel in relations:
                if not users.get(rel[0]):
                    # Get user device limit
                    user_obj = crud.get_user(db, rel[0])
                    device_limit = user_obj.device_limit if user_obj else None
                    
                    # Get allowed device fingerprints (non-blocked only)
                    devices = device_crud.get_user_devices(
                        db, 
                        rel[0], 
                        is_blocked=False,
                        limit=1000
                    )
                    allowed_fingerprints = [d.fingerprint for d in devices]
                    
                    users[rel[0]] = dict(
                        username=rel[1], 
                        id=rel[0], 
                        key=rel[2], 
                        inbounds=[],
                        device_limit=device_limit,
                        allowed_fingerprints=allowed_fingerprints
                    )
                users[rel[0]]["inbounds"].append(rel[3].tag)
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
