import logging

from sqlalchemy.orm import Session

from app.ai.tool_registry import register_tool

logger = logging.getLogger(__name__)


@register_tool(
    name="list_admins",
    description="List all admin accounts with their roles, service access, and user modification permissions.",
    requires_confirmation=False,
)
async def list_admins(db: Session, limit: int = 50, offset: int = 0) -> dict:
    from app.db import crud

    admins = crud.get_admins(db, offset=offset, limit=limit)
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
        "total": len(admins),
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
        "Modify an admin's permissions or password. Only provided fields are updated. "
        "Can change: is_sudo, enabled, password, all_services_access, "
        "modify_users_access, service_ids."
    ),
    requires_confirmation=True,
)
async def modify_admin(
    db: Session,
    username: str,
    password: str = "",
    is_sudo: bool = False,
    enabled: bool = True,
    all_services_access: bool = False,
    modify_users_access: bool = True,
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
    kwargs["is_sudo"] = is_sudo
    kwargs["enabled"] = enabled
    kwargs["all_services_access"] = all_services_access
    kwargs["modify_users_access"] = modify_users_access
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
