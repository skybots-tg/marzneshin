import logging

from sqlalchemy.orm import Session

from app.ai.tool_registry import register_tool
from app.ai.tools._common import clamp_limit

logger = logging.getLogger(__name__)


@register_tool(
    name="get_user_devices",
    description=(
        "Get tracked devices for a specific user (from database, not live node data). "
        "Shows client name, type, fingerprint, blocked status, last seen, and IPs."
    ),
    requires_confirmation=False,
)
async def get_user_devices(db: Session, username: str) -> dict:
    from app.db.models.core import User
    from app.db import device_crud

    user = db.query(User).filter(User.username == username).first()
    if not user:
        return {"error": f"User '{username}' not found"}

    devices = device_crud.get_user_devices(db, user.id)
    count = device_crud.get_devices_count(db, user.id)

    return {
        "username": username,
        "total_devices": count,
        "devices": [
            {
                "id": d.id,
                "client_name": d.client_name,
                "client_type": d.client_type,
                "display_name": d.display_name,
                "is_blocked": d.is_blocked,
                "first_seen_at": str(d.first_seen_at) if d.first_seen_at else None,
                "last_seen_at": str(d.last_seen_at) if d.last_seen_at else None,
                "last_node_id": d.last_node_id,
            }
            for d in devices
        ],
    }


@register_tool(
    name="search_devices",
    description=(
        "Search devices across all users by IP address, client_type, or node_id. "
        "Useful for diagnosing connections — e.g. find which user is connecting from a specific IP."
    ),
    requires_confirmation=False,
)
async def search_devices(
    db: Session,
    ip: str = "",
    client_type: str = "",
    node_id: int = 0,
    limit: int = 20,
) -> dict:
    from app.db import device_crud
    from app.db.models.core import User

    limit = clamp_limit(limit)
    kwargs = {"offset": 0, "limit": limit}
    if ip:
        kwargs["ip"] = ip
    if client_type:
        kwargs["client_type"] = client_type
    if node_id > 0:
        kwargs["node_id"] = node_id

    devices = device_crud.search_devices(db, **kwargs)

    user_ids = list({d.user_id for d in devices})
    users = {
        u.id: u.username
        for u in db.query(User).filter(User.id.in_(user_ids)).all()
    } if user_ids else {}

    return {
        "total": len(devices),
        "devices": [
            {
                "id": d.id,
                "user_id": d.user_id,
                "username": users.get(d.user_id, "unknown"),
                "client_name": d.client_name,
                "client_type": d.client_type,
                "is_blocked": d.is_blocked,
                "last_seen_at": str(d.last_seen_at) if d.last_seen_at else None,
                "last_node_id": d.last_node_id,
            }
            for d in devices
        ],
    }
