import asyncio
import logging

from sqlalchemy.orm import Session

from app.ai.tool_registry import register_tool

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
        "Check health status of nodes at once. Returns a summary of healthy, "
        "unhealthy, and disabled nodes plus per-node detail. Default limit 100 "
        "nodes — if you have more, call `list_nodes` with pagination instead. "
        "Summary counters always reflect the full table regardless of the cap."
    ),
    requires_confirmation=False,
)
async def check_all_nodes_health(db: Session, limit: int = 100) -> dict:
    from app.db.models import Node
    from app.marznode import node_registry

    limit = max(1, min(int(limit or 100), 200))

    total = db.query(Node).count()
    nodes = db.query(Node).order_by(Node.id).limit(limit).all()
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
            "shown": len(result),
            "truncated": total > len(result),
        },
    }


@register_tool(
    name="get_node_devices",
    description="Get connected devices on a node. Shows active client connections with IPs and client names.",
    requires_confirmation=False,
)
async def get_node_devices(db: Session, node_id: int, active_only: bool = True) -> dict:
    from app.marznode import node_registry
    db.close()
    node = node_registry.get(node_id)
    if not node:
        return {"error": f"Node {node_id} is not connected"}

    try:
        response = await node.fetch_all_devices()
    except NotImplementedError:
        return {"error": "This node does not support device listing"}
    except Exception as e:
        return {"error": f"Failed to fetch devices: {str(e)}"}

    devices = []
    for user_devices in response.users:
        for device in user_devices.devices:
            if active_only and not device.is_active:
                continue
            devices.append({
                "uid": user_devices.uid,
                "remote_ip": device.remote_ip,
                "client_name": device.client_name,
                "protocol": device.protocol if device.protocol else None,
                "is_active": device.is_active,
                "last_seen": str(device.last_seen) if device.last_seen else None,
            })

    return {"node_id": node_id, "devices": devices, "count": len(devices)}
