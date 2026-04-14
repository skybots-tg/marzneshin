import logging

from sqlalchemy.orm import Session

from app.ai.tool_registry import register_tool

logger = logging.getLogger(__name__)


@register_tool(
    name="list_users",
    description="List users with pagination. Returns username, status, traffic usage, and expiry info.",
    requires_confirmation=False,
)
async def list_users(db: Session, limit: int = 20, offset: int = 0) -> dict:
    from app.db.models.core import User
    query = db.query(User).offset(offset).limit(limit)
    users = query.all()
    total = db.query(User).count()
    return {
        "users": [
            {
                "id": u.id,
                "username": u.username,
                "status": str(u.status),
                "used_traffic": u.used_traffic,
                "data_limit": u.data_limit,
                "expire_date": str(u.expire_date) if u.expire_date else None,
                "created_at": str(u.created_at) if u.created_at else None,
                "online_at": str(u.online_at) if u.online_at else None,
                "enabled": u.enabled,
            }
            for u in users
        ],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@register_tool(
    name="get_user_info",
    description="Get detailed information about a specific user by username",
    requires_confirmation=False,
)
async def get_user_info(db: Session, username: str) -> dict:
    from app.db.models.core import User
    user = db.query(User).filter(User.username == username).first()
    if not user:
        return {"error": f"User '{username}' not found"}
    return {
        "id": user.id,
        "username": user.username,
        "status": str(user.status),
        "used_traffic": user.used_traffic,
        "data_limit": user.data_limit,
        "expire_date": str(user.expire_date) if user.expire_date else None,
        "expire_strategy": str(user.expire_strategy) if user.expire_strategy else None,
        "created_at": str(user.created_at) if user.created_at else None,
        "online_at": str(user.online_at) if user.online_at else None,
        "enabled": user.enabled,
        "removed": user.removed,
        "data_limit_reset_strategy": str(user.data_limit_reset_strategy) if user.data_limit_reset_strategy else None,
        "services": [s.name for s in user.services] if user.services else [],
    }
