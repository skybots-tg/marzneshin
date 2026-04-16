import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.ai.tool_registry import register_tool
from app.ai.tools._common import clamp_limit, clamp_offset

logger = logging.getLogger(__name__)


def _serialize_user(u) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "status": str(u.status),
        "used_traffic": u.used_traffic,
        "data_limit": u.data_limit,
        "expire_date": str(u.expire_date) if u.expire_date else None,
        "expire_strategy": str(u.expire_strategy) if u.expire_strategy else None,
        "created_at": str(u.created_at) if u.created_at else None,
        "online_at": str(u.online_at) if u.online_at else None,
        "enabled": u.enabled,
        "activated": u.activated,
        "is_active": u.is_active,
        "expired": u.expired,
        "data_limit_reached": u.data_limit_reached,
        "data_limit_reset_strategy": (
            str(u.data_limit_reset_strategy) if u.data_limit_reset_strategy else None
        ),
        "services": [
            {"id": s.id, "name": s.name} for s in u.services
        ] if u.services else [],
    }


@register_tool(
    name="list_users",
    description=(
        "List users with pagination and optional filters. "
        "ALWAYS pass a `username` filter (substring match) when looking for a "
        "specific user — installs can hold 10k+ rows. "
        "For aggregate questions ('how many users are active?') call count_users "
        "instead. Default limit is 20; hard maximum is 100."
    ),
    requires_confirmation=False,
)
async def list_users(
    db: Session,
    limit: int = 20,
    offset: int = 0,
    username: str = "",
    enabled: int = -1,
) -> dict:
    from app.db.models.core import User

    limit = clamp_limit(limit)
    offset = clamp_offset(offset)

    query = db.query(User).filter(User.removed == False)  # noqa: E712
    if username:
        query = query.filter(User.username.ilike(f"%{username}%"))
    if enabled in (0, 1):
        query = query.filter(User.enabled == bool(enabled))
    total = query.count()
    users = query.offset(offset).limit(limit).all()
    return {
        "users": [_serialize_user(u) for u in users],
        "total": total,
        "offset": offset,
        "limit": limit,
        "truncated": total > offset + limit,
    }


@register_tool(
    name="get_user_info",
    description=(
        "Get detailed information about a specific user by username. "
        "Shows traffic, limits, expiry, services, subscription info, and device limit."
    ),
    requires_confirmation=False,
)
async def get_user_info(db: Session, username: str) -> dict:
    from app.db.models.core import User

    user = db.query(User).filter(User.username == username).first()
    if not user:
        return {"error": f"User '{username}' not found"}
    result = _serialize_user(user)
    result.update({
        "removed": user.removed,
        "lifetime_used_traffic": user.lifetime_used_traffic,
        "usage_duration": user.usage_duration,
        "activation_deadline": str(user.activation_deadline) if user.activation_deadline else None,
        "device_limit": user.device_limit,
        "note": user.note,
        "sub_updated_at": str(user.sub_updated_at) if user.sub_updated_at else None,
        "sub_last_user_agent": user.sub_last_user_agent,
        "traffic_reset_at": str(user.traffic_reset_at) if user.traffic_reset_at else None,
        "sub_revoked_at": str(user.sub_revoked_at) if user.sub_revoked_at else None,
        "owner_username": user.admin.username if user.admin else None,
    })
    return result


@register_tool(
    name="create_user",
    description=(
        "Create a new user. Requires username and service_ids. "
        "expire_strategy: 'never', 'fixed_date', or 'start_on_first_use'. "
        "For fixed_date, provide expire_date (ISO format). "
        "For start_on_first_use, provide usage_duration in seconds. "
        "data_limit is in bytes (0 = unlimited). "
        "The user will be synced to nodes automatically."
    ),
    requires_confirmation=True,
)
async def create_user(
    db: Session,
    username: str,
    service_ids: list = [],
    expire_strategy: str = "never",
    expire_date: str = "",
    usage_duration: int = 0,
    data_limit: int = 0,
    data_limit_reset_strategy: str = "no_reset",
    note: str = "",
) -> dict:
    from app.models.user import UserCreate, UserExpireStrategy, UserDataUsageResetStrategy
    from app.models.admin import Admin as AdminModel
    from app.services import user_service
    from app.db.models.core import Admin

    sudo = db.query(Admin).filter(Admin.is_sudo == True).first()
    if not sudo:
        return {"error": "No sudo admin found in database"}

    parsed_expire = None
    if expire_date:
        try:
            parsed_expire = datetime.fromisoformat(expire_date)
        except ValueError:
            return {"error": f"Invalid expire_date format: {expire_date}"}

    try:
        user_create = UserCreate(
            username=username,
            service_ids=service_ids,
            expire_strategy=UserExpireStrategy(expire_strategy),
            expire_date=parsed_expire,
            usage_duration=usage_duration or None,
            data_limit=data_limit or None,
            data_limit_reset_strategy=UserDataUsageResetStrategy(data_limit_reset_strategy),
            note=note or None,
        )
    except (ValueError, Exception) as e:
        return {"error": f"Validation error: {str(e)}"}

    admin_model = AdminModel.model_validate(sudo)
    try:
        db_user = user_service.create_user(db, user_create, admin_model)
    except Exception as e:
        return {"error": str(e)}

    return {"success": True, "user": _serialize_user(db_user)}


@register_tool(
    name="modify_user",
    description=(
        "Modify an existing user. Only provided (non-empty/non-zero) fields will be updated. "
        "Can change data_limit (bytes), expire_date (ISO), expire_strategy, "
        "service_ids, data_limit_reset_strategy, note, usage_duration. "
        "Syncs changes to nodes automatically."
    ),
    requires_confirmation=True,
)
async def modify_user(
    db: Session,
    username: str,
    data_limit: int = -1,
    expire_date: str = "",
    expire_strategy: str = "",
    service_ids: list = [],
    data_limit_reset_strategy: str = "",
    usage_duration: int = -1,
    note: str = "",
) -> dict:
    from app.db import crud
    from app.models.user import UserModify, UserExpireStrategy, UserDataUsageResetStrategy
    from app.models.admin import Admin as AdminModel
    from app.services import user_service
    from app.db.models.core import Admin

    db_user = crud.get_user(db, username)
    if not db_user:
        return {"error": f"User '{username}' not found"}

    sudo = db.query(Admin).filter(Admin.is_sudo == True).first()
    admin_model = AdminModel.model_validate(sudo)

    kwargs = {}
    kwargs["username"] = username

    if data_limit >= 0:
        kwargs["data_limit"] = data_limit or None
    if expire_date:
        try:
            kwargs["expire_date"] = datetime.fromisoformat(expire_date)
        except ValueError:
            return {"error": f"Invalid expire_date: {expire_date}"}
    if expire_strategy:
        kwargs["expire_strategy"] = UserExpireStrategy(expire_strategy)
    if service_ids:
        kwargs["service_ids"] = service_ids
    if data_limit_reset_strategy:
        kwargs["data_limit_reset_strategy"] = UserDataUsageResetStrategy(data_limit_reset_strategy)
    if usage_duration >= 0:
        kwargs["usage_duration"] = usage_duration or None
    if note:
        kwargs["note"] = note

    try:
        modifications = UserModify(**kwargs)
        db_user = user_service.modify_user(db, db_user, modifications, admin_model)
    except Exception as e:
        return {"error": str(e)}

    return {"success": True, "user": _serialize_user(db_user)}


@register_tool(
    name="delete_user",
    description=(
        "Soft-delete a user by username. Removes from nodes and marks as removed in DB. "
        "This is irreversible."
    ),
    requires_confirmation=True,
)
async def delete_user(db: Session, username: str) -> dict:
    from app.db import crud
    from app.models.admin import Admin as AdminModel
    from app.services import user_service
    from app.db.models.core import Admin

    db_user = crud.get_user(db, username)
    if not db_user:
        return {"error": f"User '{username}' not found"}

    sudo = db.query(Admin).filter(Admin.is_sudo == True).first()
    admin_model = AdminModel.model_validate(sudo)

    try:
        user_service.remove_user(db, db_user, admin_model)
    except Exception as e:
        return {"error": str(e)}

    return {"success": True, "message": f"User '{username}' deleted"}


@register_tool(
    name="enable_user",
    description="Enable a disabled user. Syncs to nodes if the user becomes active.",
    requires_confirmation=True,
)
async def enable_user(db: Session, username: str) -> dict:
    from app.db import crud
    from app.models.admin import Admin as AdminModel
    from app.services import user_service
    from app.db.models.core import Admin

    db_user = crud.get_user(db, username)
    if not db_user:
        return {"error": f"User '{username}' not found"}

    sudo = db.query(Admin).filter(Admin.is_sudo == True).first()
    admin_model = AdminModel.model_validate(sudo)

    try:
        db_user = user_service.enable_user(db, db_user, admin_model)
    except Exception as e:
        return {"error": str(e)}

    return {"success": True, "user": _serialize_user(db_user)}


@register_tool(
    name="disable_user",
    description="Disable a user, removing them from all nodes.",
    requires_confirmation=True,
)
async def disable_user(db: Session, username: str) -> dict:
    from app.db import crud
    from app.models.admin import Admin as AdminModel
    from app.services import user_service
    from app.db.models.core import Admin

    db_user = crud.get_user(db, username)
    if not db_user:
        return {"error": f"User '{username}' not found"}

    sudo = db.query(Admin).filter(Admin.is_sudo == True).first()
    admin_model = AdminModel.model_validate(sudo)

    try:
        db_user = user_service.disable_user(db, db_user, admin_model)
    except Exception as e:
        return {"error": str(e)}

    return {"success": True, "user": _serialize_user(db_user)}


@register_tool(
    name="reset_user_data",
    description="Reset traffic usage for a user back to zero. May reactivate the user if they were data-limited.",
    requires_confirmation=True,
)
async def reset_user_data(db: Session, username: str) -> dict:
    from app.db import crud
    from app.models.admin import Admin as AdminModel
    from app.services import user_service
    from app.db.models.core import Admin

    db_user = crud.get_user(db, username)
    if not db_user:
        return {"error": f"User '{username}' not found"}

    sudo = db.query(Admin).filter(Admin.is_sudo == True).first()
    admin_model = AdminModel.model_validate(sudo)

    try:
        db_user = user_service.reset_data_usage(db, db_user, admin_model)
    except Exception as e:
        return {"error": str(e)}

    return {"success": True, "user": _serialize_user(db_user)}


@register_tool(
    name="revoke_user_subscription",
    description="Rotate the user's subscription key, invalidating all existing subscription links.",
    requires_confirmation=True,
)
async def revoke_user_subscription(db: Session, username: str) -> dict:
    from app.db import crud
    from app.models.admin import Admin as AdminModel
    from app.services import user_service
    from app.db.models.core import Admin

    db_user = crud.get_user(db, username)
    if not db_user:
        return {"error": f"User '{username}' not found"}

    sudo = db.query(Admin).filter(Admin.is_sudo == True).first()
    admin_model = AdminModel.model_validate(sudo)

    try:
        db_user = user_service.revoke_subscription(db, db_user, admin_model)
    except Exception as e:
        return {"error": str(e)}

    return {"success": True, "message": f"Subscription revoked for '{username}'"}


@register_tool(
    name="get_user_usage",
    description=(
        "Get traffic usage statistics for a user broken down by node. "
        "Provide start_date and end_date in ISO format (e.g. '2025-01-01'). "
        "Returns per-node traffic series and total bytes."
    ),
    requires_confirmation=False,
)
async def get_user_usage(
    db: Session, username: str, start_date: str = "", end_date: str = ""
) -> dict:
    from app.db import crud
    from datetime import timedelta

    db_user = crud.get_user(db, username)
    if not db_user:
        return {"error": f"User '{username}' not found"}

    now = datetime.now(timezone.utc)
    try:
        start = datetime.fromisoformat(start_date) if start_date else now - timedelta(days=7)
        end = datetime.fromisoformat(end_date) if end_date else now
    except ValueError as e:
        return {"error": f"Invalid date format: {str(e)}"}

    result = crud.get_user_usages(db, db_user, start, end)
    return {
        "username": result.username,
        "total_bytes": result.total,
        "node_usages": [
            {
                "node_id": nu.node_id,
                "node_name": nu.node_name,
                "total": sum(u[1] for u in nu.usages),
            }
            for nu in result.node_usages
        ],
    }
