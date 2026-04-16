import logging

from sqlalchemy.orm import Session

from app.ai.tool_registry import register_tool
from app.ai.tools._common import clamp_limit, clamp_offset, paginated_envelope

logger = logging.getLogger(__name__)


def _device_owner_username(db, user_id: int) -> str | None:
    from app.db.models.core import User
    row = db.query(User.username).filter(User.id == user_id).first()
    return row[0] if row else None


@register_tool(
    name="get_user_devices",
    description=(
        "Get tracked devices for a specific user (from database, not live node data). "
        "Shows client name, type, fingerprint, blocked status, last seen, and IPs. "
        "Paginated — default limit 50, hard max 100. Filter with `is_blocked` "
        "(-1 = any, 0 = only active, 1 = only blocked). Check `truncated` and "
        "`next_offset` in the response to paginate further."
    ),
    requires_confirmation=False,
)
async def get_user_devices(
    db: Session,
    username: str,
    limit: int = 50,
    offset: int = 0,
    is_blocked: int = -1,
) -> dict:
    from app.db.models.core import User
    from app.db import device_crud

    user = db.query(User).filter(User.username == username).first()
    if not user:
        return {"error": f"User '{username}' not found"}

    limit = clamp_limit(limit, default=50, maximum=100)
    offset = clamp_offset(offset)
    blocked_filter = bool(is_blocked) if is_blocked in (0, 1) else None

    total = device_crud.get_devices_count(db, user.id, is_blocked=blocked_filter)
    devices = device_crud.get_user_devices(
        db, user.id, offset=offset, limit=limit, is_blocked=blocked_filter
    )

    return {
        "username": username,
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
        **paginated_envelope(total, offset, limit),
    }


@register_tool(
    name="search_devices",
    description=(
        "Search devices across all users by IP / client_type / node_id / "
        "country_code / blocked state. ALWAYS pass at least one filter — "
        "the devices table can hold hundreds of thousands of rows on a busy "
        "install. Paginated: pass `offset` and `limit` (default 20, hard "
        "max 100); check `truncated` / `next_offset` in the response. "
        "`is_blocked`: -1 = any, 0 = only active, 1 = only blocked."
    ),
    requires_confirmation=False,
)
async def search_devices(
    db: Session,
    ip: str = "",
    client_type: str = "",
    node_id: int = 0,
    country_code: str = "",
    is_blocked: int = -1,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    from app.db import device_crud
    from app.db.models.core import User

    limit = clamp_limit(limit)
    offset = clamp_offset(offset)

    kwargs: dict = {"offset": offset, "limit": limit}
    if ip:
        kwargs["ip"] = ip
    if client_type:
        kwargs["client_type"] = client_type
    if node_id > 0:
        kwargs["node_id"] = node_id
    if country_code:
        kwargs["country_code"] = country_code
    if is_blocked in (0, 1):
        kwargs["is_blocked"] = bool(is_blocked)

    devices = device_crud.search_devices(db, **kwargs)

    probe_kwargs = dict(kwargs)
    probe_kwargs.update({"offset": offset + limit, "limit": 1})
    has_more = bool(device_crud.search_devices(db, **probe_kwargs))
    estimated_total = offset + len(devices) + (1 if has_more else 0)

    user_ids = list({d.user_id for d in devices})
    users = {
        u.id: u.username
        for u in db.query(User).filter(User.id.in_(user_ids)).all()
    } if user_ids else {}

    return {
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
        "offset": offset,
        "limit": limit,
        "truncated": has_more,
        "next_offset": (offset + limit) if has_more else None,
        "total_is_estimate": True,
        "total_at_least": estimated_total,
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
