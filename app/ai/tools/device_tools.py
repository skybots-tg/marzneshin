import logging

from sqlalchemy.orm import Session

from app.ai.tool_registry import register_tool
from app.ai.tools._common import clamp_limit

logger = logging.getLogger(__name__)


def _device_owner_username(db, user_id: int) -> str | None:
    from app.db.models.core import User
    row = db.query(User.username).filter(User.id == user_id).first()
    return row[0] if row else None


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


@register_tool(
    name="block_device",
    description=(
        "Mark a specific device as blocked (UserDevice.is_blocked=True). "
        "Requires `device_id` — first resolve it via get_user_devices or "
        "search_devices. When ENFORCE_DEVICE_LIMITS_ON_PROXY is enabled, "
        "marznode will drop connections from this device on the next sync. "
        "Blocking is reversible with unblock_device. Use this instead of "
        "lowering device_limit when you want to disable ONE specific client "
        "without touching the user's other devices."
    ),
    requires_confirmation=True,
)
async def block_device(db: Session, device_id: int) -> dict:
    from app.db import device_crud

    device = device_crud.get_device_by_id(db, device_id)
    if not device:
        return {"error": f"Device {device_id} not found"}
    if device.is_blocked:
        return {
            "success": True,
            "already_blocked": True,
            "device_id": device_id,
            "user_id": device.user_id,
            "username": _device_owner_username(db, device.user_id),
        }

    updated = device_crud.update_device(db, device_id, is_blocked=True)
    return {
        "success": True,
        "device_id": device_id,
        "user_id": updated.user_id,
        "username": _device_owner_username(db, updated.user_id),
        "client_name": updated.client_name,
        "is_blocked": updated.is_blocked,
    }


@register_tool(
    name="unblock_device",
    description=(
        "Clear the blocked flag on a device (UserDevice.is_blocked=False). "
        "Inverse of block_device."
    ),
    requires_confirmation=True,
)
async def unblock_device(db: Session, device_id: int) -> dict:
    from app.db import device_crud

    device = device_crud.get_device_by_id(db, device_id)
    if not device:
        return {"error": f"Device {device_id} not found"}
    if not device.is_blocked:
        return {
            "success": True,
            "already_unblocked": True,
            "device_id": device_id,
            "user_id": device.user_id,
            "username": _device_owner_username(db, device.user_id),
        }

    updated = device_crud.update_device(db, device_id, is_blocked=False)
    return {
        "success": True,
        "device_id": device_id,
        "user_id": updated.user_id,
        "username": _device_owner_username(db, updated.user_id),
        "client_name": updated.client_name,
        "is_blocked": updated.is_blocked,
    }


@register_tool(
    name="forget_device",
    description=(
        "DANGEROUS: permanently delete a device record and ALL its related "
        "IP / traffic rows. Use only when the admin explicitly wants to drop "
        "historical data — for everyday cases prefer block_device (reversible)."
    ),
    requires_confirmation=True,
)
async def forget_device(db: Session, device_id: int) -> dict:
    from app.db import device_crud

    device = device_crud.get_device_by_id(db, device_id)
    if not device:
        return {"error": f"Device {device_id} not found"}

    owner = _device_owner_username(db, device.user_id)
    ok = device_crud.delete_device(db, device_id)
    if not ok:
        return {"error": f"Failed to delete device {device_id}"}
    return {
        "success": True,
        "device_id": device_id,
        "username": owner,
    }


@register_tool(
    name="get_user_device_stats",
    description=(
        "Get aggregated device statistics for a user: total / active (seen in "
        "last 24h) / blocked device counts, unique IPs, unique country codes, "
        "lifetime traffic. Cheaper than listing all devices when you only need "
        "the numbers."
    ),
    requires_confirmation=False,
)
async def get_user_device_stats(db: Session, username: str) -> dict:
    from app.db import device_crud
    from app.db.models.core import User

    user = db.query(User).filter(User.username == username).first()
    if not user:
        return {"error": f"User '{username}' not found"}

    stats = device_crud.get_user_device_statistics(db, user.id)
    stats["username"] = username
    stats["device_limit"] = user.device_limit
    return stats
