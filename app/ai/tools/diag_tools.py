import asyncio
import logging

from sqlalchemy.orm import Session

from app.ai.tool_registry import register_tool
from app.ai.tools._common import clamp_limit, clamp_offset, paginated_envelope

logger = logging.getLogger(__name__)


@register_tool(
    name="get_node_logs",
    description="Get recent log lines from a node backend. Useful for diagnosing issues.",
    requires_confirmation=False,
)
async def get_node_logs(db: Session, node_id: int, backend: str = "xray", max_lines: int = 50) -> dict:
    from app.marznode import node_registry
    db.close()
    node = node_registry.get(node_id)
    if not node:
        return {"error": f"Node {node_id} is not connected"}

    lines = []

    async def _collect():
        async for line in node.get_logs(name=backend, include_buffer=True):
            lines.append(line)
            if len(lines) >= max_lines:
                break

    try:
        await asyncio.wait_for(_collect(), timeout=30.0)
    except asyncio.TimeoutError:
        return {
            "error": (
                "Timed out after 30s while reading log stream. "
                "The node may be overloaded or the gRPC stream stalled."
            ),
            "partial_lines": lines,
            "node_id": node_id,
            "backend": backend,
        }
    except asyncio.CancelledError:
        pass
    except Exception as e:
        return {"error": f"Failed to get logs: {str(e)}", "partial_lines": lines}

    return {"node_id": node_id, "backend": backend, "lines": lines, "count": len(lines)}


@register_tool(
    name="check_all_nodes_health",
    description=(
        "Check health status of nodes with pagination. Per-node detail for "
        "the requested page plus an always-accurate summary of healthy / "
        "unhealthy / disabled counts across the full table. Default limit "
        "50, hard max 100. Use `offset` / `next_offset` to walk all nodes "
        "if you have more than one page."
    ),
    requires_confirmation=False,
)
async def check_all_nodes_health(
    db: Session, limit: int = 50, offset: int = 0
) -> dict:
    from app.db.models import Node
    from app.marznode import node_registry

    limit = clamp_limit(limit, default=50, maximum=100)
    offset = clamp_offset(offset)

    total = db.query(Node).count()
    nodes = db.query(Node).order_by(Node.id).offset(offset).limit(limit).all()
    result = []
    for n in nodes:
        connected = node_registry.get(n.id) is not None
        result.append({
            "id": n.id,
            "name": n.name,
            "status": str(n.status),
            "connected": connected,
            "message": n.message,
            "last_status_change": str(n.last_status_change) if n.last_status_change else None,
        })

    from app.models.node import NodeStatus
    healthy_total = db.query(Node).filter(Node.status == NodeStatus.healthy).count()
    unhealthy_total = db.query(Node).filter(Node.status == NodeStatus.unhealthy).count()
    disabled_total = db.query(Node).filter(Node.status == NodeStatus.disabled).count()

    return {
        "nodes": result,
        "summary": {
            "total": total,
            "healthy": healthy_total,
            "unhealthy": unhealthy_total,
            "disabled": disabled_total,
        },
        **paginated_envelope(total, offset, limit),
    }


@register_tool(
    name="get_node_devices",
    description=(
        "Get live connected devices on a node (streamed once from marznode, "
        "not paginated on the node side). Returns every device matching the "
        "filters, then the panel applies `limit` (default 100, hard max 500) "
        "and `offset` in-memory so the agent can still read in pages. "
        "`active_only=True` skips inactive entries. Filters: "
        "`uid_substring` (substring of the marznode UID, typically the "
        "username), `ip_substring` (substring of the remote IP). "
        "Response includes `truncated` and `next_offset` for the next page."
    ),
    requires_confirmation=False,
)
async def get_node_devices(
    db: Session,
    node_id: int,
    active_only: bool = True,
    limit: int = 100,
    offset: int = 0,
    uid_substring: str = "",
    ip_substring: str = "",
) -> dict:
    from app.marznode import node_registry
    db.close()
    node = node_registry.get(node_id)
    if not node:
        return {"error": f"Node {node_id} is not connected"}

    limit = clamp_limit(limit, default=100, maximum=500)
    offset = clamp_offset(offset)

    try:
        response = await node.fetch_all_devices()
    except NotImplementedError:
        return {"error": "This node does not support device listing"}
    except Exception as e:
        return {"error": f"Failed to fetch devices: {str(e)}"}

    all_devices: list[dict] = []
    for user_devices in response.users:
        uid = user_devices.uid
        if uid_substring and uid_substring.lower() not in (uid or "").lower():
            continue
        for device in user_devices.devices:
            if active_only and not device.is_active:
                continue
            if ip_substring and ip_substring not in (device.remote_ip or ""):
                continue
            all_devices.append({
                "uid": uid,
                "remote_ip": device.remote_ip,
                "client_name": device.client_name,
                "protocol": device.protocol if device.protocol else None,
                "is_active": device.is_active,
                "last_seen": str(device.last_seen) if device.last_seen else None,
            })

    total = len(all_devices)
    page = all_devices[offset:offset + limit]

    return {
        "node_id": node_id,
        "devices": page,
        "active_only": active_only,
        **paginated_envelope(total, offset, limit),
    }
