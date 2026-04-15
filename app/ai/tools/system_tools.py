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
        "List all services with their IDs, names, inbound tags, and user count. "
        "Users are attached to services, and services contain inbounds (which have hosts). "
        "Relationship: User → Service → Inbound → Host."
    ),
    requires_confirmation=False,
)
async def list_services(db: Session) -> dict:
    from app.db.models.core import Service
    services = db.query(Service).all()
    return {
        "services": [
            {
                "id": s.id,
                "name": s.name,
                "user_count": len(s.users) if s.users else 0,
                "inbounds": [
                    {
                        "id": i.id,
                        "tag": i.tag,
                        "protocol": str(i.protocol),
                        "node_id": i.node_id,
                        "host_count": len(i.hosts) if i.hosts else 0,
                    }
                    for i in s.inbounds
                ] if s.inbounds else [],
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
