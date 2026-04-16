import logging

from sqlalchemy.orm import Session

from app.ai.tool_registry import register_tool
from app.ai.tools._common import clamp_limit, clamp_offset

logger = logging.getLogger(__name__)


@register_tool(
    name="list_admins",
    description=(
        "List admin accounts with pagination. Default limit 20, hard maximum 100. "
        "Returns roles, service access, and user modification permissions. "
        "Pass `username` for a substring filter."
    ),
    requires_confirmation=False,
)
async def list_admins(
    db: Session, limit: int = 20, offset: int = 0, username: str = ""
) -> dict:
    from app.db.models.core import Admin

    limit = clamp_limit(limit)
    offset = clamp_offset(offset)

    query = db.query(Admin)
    if username:
        query = query.filter(Admin.username.ilike(f"%{username}%"))
    total = query.count()
    admins = query.order_by(Admin.id).offset(offset).limit(limit).all()

    return {
        "admins": [
            {
                "id": a.id,
                "username": a.username,
                "is_sudo": a.is_sudo,
                "enabled": a.enabled,
                "all_services_access": a.all_services_access,
                "modify_users_access": a.modify_users_access,
                "services": [
                    {"id": s.id, "name": s.name} for s in a.services
                ] if a.services else [],
            }
            for a in admins
        ],
        "total": total,
        "offset": offset,
        "limit": limit,
        "truncated": total > offset + limit,
    }


@register_tool(
    name="get_admin_info",
    description="Get detailed information about an admin by username, including services and permissions.",
    requires_confirmation=False,
)
async def get_admin_info(db: Session, username: str) -> dict:
    from app.db import crud

    admin = crud.get_admin(db, username)
    if not admin:
        return {"error": f"Admin '{username}' not found"}

    return {
        "id": admin.id,
        "username": admin.username,
        "is_sudo": admin.is_sudo,
        "enabled": admin.enabled,
        "all_services_access": admin.all_services_access,
        "modify_users_access": admin.modify_users_access,
        "subscription_url_prefix": admin.subscription_url_prefix or "",
        "services": [
            {"id": s.id, "name": s.name} for s in admin.services
        ] if admin.services else [],
        "created_at": str(admin.created_at) if admin.created_at else None,
        "password_reset_at": str(admin.password_reset_at) if admin.password_reset_at else None,
    }


@register_tool(
    name="create_admin",
    description=(
        "Create a new admin account. Provide username, password, and permissions. "
        "service_ids controls which services the admin can manage (empty = none, "
        "or set all_services_access=true for full access)."
    ),
    requires_confirmation=True,
)
async def create_admin(
    db: Session,
    username: str,
    password: str,
    is_sudo: bool = False,
    all_services_access: bool = False,
    modify_users_access: bool = True,
    service_ids: list = [],
) -> dict:
    from app.db import crud
    from app.models.admin import AdminCreate

    existing = crud.get_admin(db, username)
    if existing:
        return {"error": f"Admin '{username}' already exists"}

    try:
        admin_data = AdminCreate(
            username=username,
            password=password,
            is_sudo=is_sudo,
            all_services_access=all_services_access,
            modify_users_access=modify_users_access,
            service_ids=service_ids,
        )
        db_admin = crud.create_admin(db, admin_data)
    except Exception as e:
        return {"error": str(e)}

    return {
        "success": True,
        "admin": {
            "id": db_admin.id,
            "username": db_admin.username,
            "is_sudo": db_admin.is_sudo,
            "enabled": db_admin.enabled,
        },
    }


@register_tool(
    name="modify_admin",
    description=(
        "Modify an admin's permissions or password. Only fields whose values differ "
        "from the sentinel are applied — empty strings, empty lists, and -1 are "
        "ignored. For boolean flags (is_sudo, enabled, all_services_access, "
        "modify_users_access) pass 1 to enable, 0 to disable, or -1 to keep unchanged."
    ),
    requires_confirmation=True,
)
async def modify_admin(
    db: Session,
    username: str,
    password: str = "",
    is_sudo: int = -1,
    enabled: int = -1,
    all_services_access: int = -1,
    modify_users_access: int = -1,
    service_ids: list = [],
) -> dict:
    from app.db import crud
    from app.models.admin import AdminPartialModify

    db_admin = crud.get_admin(db, username)
    if not db_admin:
        return {"error": f"Admin '{username}' not found"}

    kwargs = {}
    if password:
        kwargs["password"] = password
    if is_sudo in (0, 1):
        kwargs["is_sudo"] = bool(is_sudo)
    if enabled in (0, 1):
        kwargs["enabled"] = bool(enabled)
    if all_services_access in (0, 1):
        kwargs["all_services_access"] = bool(all_services_access)
    if modify_users_access in (0, 1):
        kwargs["modify_users_access"] = bool(modify_users_access)
    if service_ids:
        kwargs["service_ids"] = service_ids

    try:
        modifications = AdminPartialModify(**kwargs)
        db_admin = crud.update_admin(db, db_admin, modifications)
    except Exception as e:
        return {"error": str(e)}

    return {
        "success": True,
        "admin": {
            "id": db_admin.id,
            "username": db_admin.username,
            "is_sudo": db_admin.is_sudo,
            "enabled": db_admin.enabled,
            "all_services_access": db_admin.all_services_access,
            "modify_users_access": db_admin.modify_users_access,
        },
    }


@register_tool(
    name="delete_admin",
    description=(
        "DANGEROUS: permanently delete an admin account. "
        "Users owned by this admin are NOT deleted — check `count_users` with "
        "`admin_username` first to see the blast radius and reassign/clean them "
        "beforehand if needed. Refuses to delete the last sudo admin — the "
        "panel needs at least one."
    ),
    requires_confirmation=True,
)
async def delete_admin(db: Session, username: str) -> dict:
    from app.db import crud
    from app.db.models.core import Admin, User

    db_admin = crud.get_admin(db, username)
    if not db_admin:
        return {"error": f"Admin '{username}' not found"}

    if db_admin.is_sudo:
        remaining_sudo = (
            db.query(Admin)
            .filter(Admin.is_sudo == True, Admin.id != db_admin.id)  # noqa: E712
            .count()
        )
        if remaining_sudo == 0:
            return {
                "error": (
                    f"Refusing to delete '{username}': it is the last sudo admin. "
                    "Promote another admin with modify_admin(is_sudo=1) first."
                )
            }

    owned_users = (
        db.query(User).filter(User.admin_id == db_admin.id, User.removed == False)  # noqa: E712
        .count()
    )

    try:
        crud.remove_admin(db, db_admin)
    except Exception as e:
        db.rollback()
        return {"error": f"Failed to delete admin: {str(e)}"}

    return {
        "success": True,
        "message": f"Admin '{username}' deleted",
        "orphaned_users": owned_users,
    }
