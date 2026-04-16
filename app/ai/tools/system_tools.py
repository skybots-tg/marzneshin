import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.ai.tool_registry import register_tool

logger = logging.getLogger(__name__)


@register_tool(
    name="get_system_info",
    description="Get general system information: total nodes, users, healthy/unhealthy counts, traffic stats",
    requires_confirmation=False,
)
async def get_system_info(db: Session) -> dict:
    from app.db.models import Node
    from app.db.models.core import Admin, User, Service
    from app.models.node import NodeStatus

    total_nodes = db.query(Node).count()
    healthy = db.query(Node).filter(Node.status == NodeStatus.healthy).count()
    unhealthy = db.query(Node).filter(Node.status == NodeStatus.unhealthy).count()
    disabled = db.query(Node).filter(Node.status == NodeStatus.disabled).count()
    total_users = db.query(User).count()
    total_admins = db.query(Admin).count()
    total_services = db.query(Service).count()

    return {
        "nodes": {
            "total": total_nodes,
            "healthy": healthy,
            "unhealthy": unhealthy,
            "disabled": disabled,
        },
        "users": {"total": total_users},
        "admins": {"total": total_admins},
        "services": {"total": total_services},
    }


@register_tool(
    name="list_services",
    description=(
        "List all services with their IDs, names, inbound tags, and user counts. "
        "User counts are computed via aggregate queries, not by loading all users, "
        "so this is safe on large installs. "
        "Relationship: User → Service → Inbound → Host."
    ),
    requires_confirmation=False,
)
async def list_services(db: Session) -> dict:
    from sqlalchemy import func
    from app.db.models.core import Service
    from app.db.models.associations import users_services

    services = db.query(Service).all()

    user_counts_rows = (
        db.query(users_services.c.service_id, func.count(users_services.c.user_id))
        .group_by(users_services.c.service_id)
        .all()
    )
    user_counts = {row[0]: row[1] for row in user_counts_rows}

    return {
        "services": [
            {
                "id": s.id,
                "name": s.name,
                "user_count": int(user_counts.get(s.id, 0)),
                "inbounds": [
                    {
                        "id": i.id,
                        "tag": i.tag,
                        "protocol": str(i.protocol),
                        "node_id": i.node_id,
                    }
                    for i in (s.inbounds or [])
                ],
            }
            for s in services
        ],
        "total": len(services),
    }


@register_tool(
    name="list_inbounds",
    description="List all inbounds across all nodes with protocol and tag info",
    requires_confirmation=False,
)
async def list_inbounds(db: Session) -> dict:
    from app.db.models.proxy import Inbound
    inbounds = db.query(Inbound).all()
    return {
        "inbounds": [
            {
                "id": i.id,
                "protocol": str(i.protocol),
                "tag": i.tag,
                "node_id": i.node_id,
            }
            for i in inbounds
        ],
        "total": len(inbounds),
    }


@register_tool(
    name="get_user_stats",
    description=(
        "Get user count statistics: total, active, expired, data-limited, "
        "enabled, disabled, online (last 30s)."
    ),
    requires_confirmation=False,
)
async def get_user_stats(db: Session) -> dict:
    from app.db.models.core import User

    total = db.query(User).filter(User.removed == False).count()
    active = db.query(User).filter(User.removed == False, User.is_active == True).count()
    expired = db.query(User).filter(User.removed == False, User.expired == True).count()
    data_limited = db.query(User).filter(User.removed == False, User.data_limit_reached == True).count()
    enabled = db.query(User).filter(User.removed == False, User.enabled == True).count()
    disabled = db.query(User).filter(User.removed == False, User.enabled == False).count()
    online_cutoff = datetime.utcnow() - timedelta(seconds=30)
    online = db.query(User).filter(User.removed == False, User.online_at > online_cutoff).count()

    return {
        "total": total,
        "active": active,
        "expired": expired,
        "data_limit_reached": data_limited,
        "enabled": enabled,
        "disabled": disabled,
        "online": online,
    }


@register_tool(
    name="get_traffic_stats",
    description=(
        "Get system-wide traffic statistics for a date range. "
        "Provide start_date and end_date in ISO format. "
        "Returns total bytes and hourly breakdown."
    ),
    requires_confirmation=False,
)
async def get_traffic_stats(
    db: Session, start_date: str = "", end_date: str = ""
) -> dict:
    from app.db import crud
    from app.db.models.core import Admin

    now = datetime.now(timezone.utc)
    try:
        start = datetime.fromisoformat(start_date) if start_date else now - timedelta(days=1)
        end = datetime.fromisoformat(end_date) if end_date else now
    except ValueError as e:
        return {"error": f"Invalid date format: {str(e)}"}

    sudo = db.query(Admin).filter(Admin.is_sudo == True).first()
    if not sudo:
        return {"error": "No sudo admin found"}

    from app.models.admin import Admin as AdminModel
    admin_model = AdminModel.model_validate(sudo)

    result = crud.get_total_usages(db, admin_model, start, end)
    return {
        "total_bytes": result.total,
        "period": {"start": str(start), "end": str(end)},
        "data_points": len(result.usages),
    }


@register_tool(
    name="count_users",
    description=(
        "Count users matching optional filters WITHOUT loading their records. "
        "Use this instead of list_users whenever you only need a number, e.g. "
        "'how many users will be affected by this change?'. "
        "Filters: "
        "enabled (True/False), active (True = currently usable), expired, "
        "data_limit_reached, service_id (>0 to restrict to one service), "
        "admin_username (owner). "
        "Returns the matching count only — safe on installs with 10k+ users."
    ),
    requires_confirmation=False,
)
async def count_users(
    db: Session,
    enabled: int = -1,
    active: int = -1,
    expired: int = -1,
    data_limit_reached: int = -1,
    service_id: int = 0,
    admin_username: str = "",
) -> dict:
    from app.db.models.core import User, Admin
    from app.db.models.associations import users_services

    query = db.query(User).filter(User.removed == False)  # noqa: E712
    if enabled in (0, 1):
        query = query.filter(User.enabled == bool(enabled))
    if active in (0, 1):
        query = query.filter(User.is_active == bool(active))
    if expired in (0, 1):
        query = query.filter(User.expired == bool(expired))
    if data_limit_reached in (0, 1):
        query = query.filter(User.data_limit_reached == bool(data_limit_reached))
    if service_id > 0:
        query = query.join(users_services, users_services.c.user_id == User.id).filter(
            users_services.c.service_id == service_id
        )
    if admin_username:
        admin = db.query(Admin).filter(Admin.username == admin_username).first()
        if not admin:
            return {"error": f"Admin '{admin_username}' not found"}
        query = query.filter(User.admin_id == admin.id)

    return {"count": query.count()}


@register_tool(
    name="count_hosts",
    description=(
        "Count hosts matching optional filters WITHOUT loading the records. "
        "Filters: inbound_id (>0 to restrict), universal_only, disabled. "
        "Useful before bulk modifications to verify the scope."
    ),
    requires_confirmation=False,
)
async def count_hosts(
    db: Session,
    inbound_id: int = 0,
    universal_only: bool = False,
    disabled: int = -1,
) -> dict:
    from app.db.models import InboundHost

    query = db.query(InboundHost)
    if inbound_id > 0:
        query = query.filter(InboundHost.inbound_id == inbound_id)
    if universal_only:
        query = query.filter(InboundHost.universal == True, InboundHost.inbound_id.is_(None))  # noqa: E712
    if disabled in (0, 1):
        query = query.filter(InboundHost.is_disabled == bool(disabled))

    return {"count": query.count()}


@register_tool(
    name="get_node_traffic",
    description=(
        "Get traffic statistics for a specific node over a date range. "
        "Provide node_id, start_date and end_date in ISO format."
    ),
    requires_confirmation=False,
)
async def get_node_traffic(
    db: Session, node_id: int, start_date: str = "", end_date: str = ""
) -> dict:
    from app.db import crud

    node = crud.get_node_by_id(db, node_id)
    if not node:
        return {"error": f"Node {node_id} not found"}

    now = datetime.now(timezone.utc)
    try:
        start = datetime.fromisoformat(start_date) if start_date else now - timedelta(days=1)
        end = datetime.fromisoformat(end_date) if end_date else now
    except ValueError as e:
        return {"error": f"Invalid date format: {str(e)}"}

    result = crud.get_node_usage(db, start, end, node)
    return {
        "node_id": node_id,
        "node_name": node.name,
        "total_bytes": result.total,
        "period": {"start": str(start), "end": str(end)},
        "data_points": len(result.usages),
    }
