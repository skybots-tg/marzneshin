import logging

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
