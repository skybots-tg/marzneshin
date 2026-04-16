import logging

from sqlalchemy.orm import Session

from app.ai.tool_registry import register_tool
from app.ai.tools._common import clamp_limit, clamp_offset

logger = logging.getLogger(__name__)


@register_tool(
    name="list_nodes",
    description=(
        "List nodes (paginated) with statuses, addresses and basic info. "
        "Default limit 50, hard max 100. Filters: `status` ('healthy', "
        "'unhealthy', 'disabled'), `name` (substring match). For a single "
        "node use `get_node_info` directly."
    ),
    requires_confirmation=False,
)
async def list_nodes(
    db: Session, limit: int = 50, offset: int = 0, status: str = "", name: str = ""
) -> dict:
    from app.db.models import Node

    limit = clamp_limit(limit, default=50, maximum=100)
    offset = clamp_offset(offset)

    query = db.query(Node)
    if status:
        query = query.filter(Node.status == status)
    if name:
        query = query.filter(Node.name.ilike(f"%{name}%"))
    total = query.count()
    nodes = query.order_by(Node.id).offset(offset).limit(limit).all()

    return {
        "nodes": [
            {
                "id": n.id,
                "name": n.name,
                "address": n.address,
                "port": n.port,
                "status": str(n.status),
                "xray_version": n.xray_version,
                "connection_backend": n.connection_backend,
                "message": n.message,
                "usage_coefficient": n.usage_coefficient,
                "uplink": n.uplink,
                "downlink": n.downlink,
            }
            for n in nodes
        ],
        "total": total,
        "offset": offset,
        "limit": limit,
        "truncated": total > offset + limit,
    }


@register_tool(
    name="get_node_info",
    description="Get detailed information about a specific node by its ID, including backends and inbounds",
    requires_confirmation=False,
)
async def get_node_info(db: Session, node_id: int) -> dict:
    from app.db.models import Node
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        return {"error": f"Node {node_id} not found"}
    return {
        "id": node.id,
        "name": node.name,
        "address": node.address,
        "port": node.port,
        "status": str(node.status),
        "xray_version": node.xray_version,
        "connection_backend": node.connection_backend,
        "message": node.message,
        "usage_coefficient": node.usage_coefficient,
        "uplink": node.uplink,
        "downlink": node.downlink,
        "created_at": str(node.created_at) if node.created_at else None,
        "last_status_change": str(node.last_status_change) if node.last_status_change else None,
        "backends": [
            {"name": b.name, "type": b.backend_type, "version": b.version, "running": b.running}
            for b in node.backends
        ],
        "inbounds": [
            {"id": i.id, "protocol": str(i.protocol), "tag": i.tag}
            for i in node.inbounds
        ],
    }


@register_tool(
    name="get_node_config",
    description=(
        "Get the live backend config (e.g. Xray JSON) of a specific node. "
        "Returns the raw config string. By default the payload is capped at "
        "32 KiB to avoid dumping huge configs into the chat — set "
        "`max_bytes` higher (up to 262144) when you genuinely need the full "
        "text for rewriting. `summary=true` returns only a compact digest "
        "(inbound tags/ports/protocols + outbound tags) instead of the full JSON."
    ),
    requires_confirmation=False,
)
async def get_node_config(
    db: Session,
    node_id: int,
    backend: str = "xray",
    max_bytes: int = 32768,
    summary: bool = False,
) -> dict:
    import json

    from app.marznode import node_registry
    db.close()
    node = node_registry.get(node_id)
    if not node:
        return {"error": f"Node {node_id} is not connected"}
    try:
        config, config_format = await node.get_backend_config(name=backend)
    except Exception as e:
        return {"error": f"Failed to get config: {str(e)}"}

    size = len(config) if config else 0

    if summary:
        digest: dict = {"node_id": node_id, "backend": backend, "size_bytes": size}
        try:
            parsed = json.loads(config)
        except (json.JSONDecodeError, TypeError):
            digest["parse_error"] = "Config is not valid JSON"
            return digest
        inbounds_summary = []
        for ib in (parsed.get("inbounds") or []):
            inbounds_summary.append({
                "tag": ib.get("tag"),
                "protocol": ib.get("protocol"),
                "port": ib.get("port"),
                "listen": ib.get("listen"),
                "streamSettings_network": (ib.get("streamSettings") or {}).get("network"),
                "streamSettings_security": (ib.get("streamSettings") or {}).get("security"),
            })
        outbounds_summary = [
            {"tag": o.get("tag"), "protocol": o.get("protocol")}
            for o in (parsed.get("outbounds") or [])
        ]
        digest.update({
            "inbounds": inbounds_summary,
            "outbounds": outbounds_summary,
            "routing_rules_count": len(((parsed.get("routing") or {}).get("rules") or [])),
        })
        return digest

    cap = max(1024, min(int(max_bytes or 32768), 262144))
    truncated = size > cap
    body = config[:cap] if truncated else config
    return {
        "config": body,
        "format": config_format,
        "size_bytes": size,
        "truncated": truncated,
        "max_bytes": cap,
    }


@register_tool(
    name="get_node_stats",
    description="Get backend runtime stats (running status) for a specific node",
    requires_confirmation=False,
)
async def get_node_stats(db: Session, node_id: int, backend: str = "xray") -> dict:
    from app.marznode import node_registry
    db.close()
    node = node_registry.get(node_id)
    if not node:
        return {"error": f"Node {node_id} is not connected"}
    try:
        stats = await node.get_backend_stats(backend)
        return {"running": stats.running}
    except Exception as e:
        return {"error": f"Failed to get stats: {str(e)}"}


@register_tool(
    name="update_node_config",
    description="Update the backend config (e.g. Xray JSON) on a node and restart the backend. This is a dangerous operation.",
    requires_confirmation=True,
)
async def update_node_config(db: Session, node_id: int, config: str, backend: str = "xray") -> dict:
    from app.marznode import node_registry
    db.close()
    node = node_registry.get(node_id)
    if not node:
        return {"error": f"Node {node_id} is not connected"}
    try:
        await node.restart_backend(name=backend, config=config, config_format=1)
        return {"success": True, "message": f"Backend '{backend}' on node {node_id} restarted with new config"}
    except Exception as e:
        return {"error": f"Failed to update config: {str(e)}"}


@register_tool(
    name="restart_node_backend",
    description="Restart a backend on a node with its current config. Use when the backend needs a restart without config changes.",
    requires_confirmation=True,
)
async def restart_node_backend(db: Session, node_id: int, backend: str = "xray") -> dict:
    from app.marznode import node_registry
    db.close()
    node = node_registry.get(node_id)
    if not node:
        return {"error": f"Node {node_id} is not connected"}
    try:
        config, config_format = await node.get_backend_config(name=backend)
        await node.restart_backend(name=backend, config=config, config_format=int(config_format))
        return {"success": True, "message": f"Backend '{backend}' on node {node_id} restarted"}
    except Exception as e:
        return {"error": f"Failed to restart: {str(e)}"}


@register_tool(
    name="resync_node_users",
    description="Force resync all users with a specific node. Ensures the node has up-to-date user data.",
    requires_confirmation=True,
)
async def resync_node_users(db: Session, node_id: int) -> dict:
    from app.marznode import node_registry
    db.close()
    node = node_registry.get(node_id)
    if not node:
        return {"error": f"Node {node_id} is not connected"}
    try:
        await node.resync_users()
        return {"success": True, "message": f"Users resynced on node {node_id}"}
    except Exception as e:
        return {"error": f"Failed to resync: {str(e)}"}


@register_tool(
    name="modify_node",
    description="Modify node parameters such as name, address, port, status, or usage_coefficient",
    requires_confirmation=True,
)
async def modify_node(
    db: Session,
    node_id: int,
    name: str = "",
    address: str = "",
    port: int = 0,
    status: str = "",
    usage_coefficient: float = -1,
) -> dict:
    from app.db import crud
    from app.models.node import NodeModify, NodeStatus

    db_node = crud.get_node_by_id(db, node_id)
    if not db_node:
        return {"error": f"Node {node_id} not found"}

    modify = NodeModify(
        name=name if name else None,
        address=address if address else None,
        port=port if port > 0 else None,
        status=NodeStatus(status) if status else None,
        usage_coefficient=usage_coefficient if usage_coefficient >= 0 else None,
    )
    updated = crud.update_node(db, db_node, modify)
    return {
        "success": True,
        "node": {
            "id": updated.id,
            "name": updated.name,
            "address": updated.address,
            "port": updated.port,
            "status": str(updated.status),
        },
    }


@register_tool(
    name="disable_node",
    description="Disable a node, preventing it from being used",
    requires_confirmation=True,
)
async def disable_node(db: Session, node_id: int) -> dict:
    from app.db import crud
    from app.models.node import NodeModify, NodeStatus
    from app.marznode import operations

    db_node = crud.get_node_by_id(db, node_id)
    if not db_node:
        return {"error": f"Node {node_id} not found"}

    modify = NodeModify(status=NodeStatus.disabled)
    crud.update_node(db, db_node, modify)
    db.close()
    await operations.remove_node(node_id)
    return {"success": True, "message": f"Node {node_id} disabled"}


@register_tool(
    name="enable_node",
    description="Enable a previously disabled node and reconnect it",
    requires_confirmation=True,
)
async def enable_node(db: Session, node_id: int) -> dict:
    from app.db import crud, get_tls_certificate
    from app.models.node import NodeModify, NodeStatus
    from app.marznode import operations

    db_node = crud.get_node_by_id(db, node_id)
    if not db_node:
        return {"error": f"Node {node_id} not found"}

    modify = NodeModify(status=NodeStatus.unhealthy)
    crud.update_node(db, db_node, modify)
    certificate = get_tls_certificate(db)
    db.close()
    await operations.add_node(db_node, certificate)
    return {"success": True, "message": f"Node {node_id} enabled and reconnecting"}


@register_tool(
    name="create_node",
    description=(
        "Create a new node in the panel and connect to it. "
        "The marznode service must already be installed and reachable at address:port. "
        "Use port 53042 unless the operator explicitly specifies another. "
        "The node becomes usable only after the gRPC handshake succeeds; monitor with "
        "get_node_info or check_all_nodes_health. Use a short unique `name`."
    ),
    requires_confirmation=True,
)
async def create_node(
    db: Session,
    name: str,
    address: str,
    port: int = 53042,
    usage_coefficient: float = 1.0,
    connection_backend: str = "grpclib",
) -> dict:
    import sqlalchemy
    from app.db import crud, get_tls_certificate
    from app.marznode import operations
    from app.models.node import NodeCreate, NodeConnectionBackend

    if not name.strip():
        return {"error": "Node name must not be empty"}
    if not address.strip():
        return {"error": "Node address must not be empty"}
    if port <= 0 or port > 65535:
        return {"error": f"Port out of range: {port}"}

    try:
        backend = NodeConnectionBackend(connection_backend)
    except ValueError:
        return {
            "error": (
                f"Invalid connection_backend '{connection_backend}'. "
                f"Allowed: grpclib, grpcio."
            )
        }

    try:
        node_create = NodeCreate(
            name=name.strip(),
            address=address.strip(),
            port=port,
            usage_coefficient=usage_coefficient,
            connection_backend=backend,
        )
    except Exception as e:
        return {"error": f"Validation error: {str(e)}"}

    try:
        db_node = crud.create_node(db, node_create)
    except sqlalchemy.exc.IntegrityError:
        db.rollback()
        return {"error": f"Node with name '{name}' already exists"}
    except Exception as e:
        db.rollback()
        return {"error": f"Failed to create node: {str(e)}"}

    certificate = get_tls_certificate(db)
    node_id = db_node.id
    node_name = db_node.name
    try:
        await operations.add_node(db_node, certificate)
    except Exception as e:
        logger.warning("Node %s created but failed to connect: %s", node_id, e)
        return {
            "success": True,
            "warning": f"Node created but initial connection failed: {str(e)}",
            "node": {"id": node_id, "name": node_name, "address": address, "port": port},
        }

    return {
        "success": True,
        "node": {
            "id": node_id,
            "name": node_name,
            "address": address,
            "port": port,
            "usage_coefficient": usage_coefficient,
        },
    }


@register_tool(
    name="delete_node",
    description=(
        "DANGEROUS: permanently delete a node from the panel. "
        "This also wipes all historical traffic rows for that node. "
        "Prefer disable_node for temporary removal. "
        "Always confirm with the operator which node_id is meant before calling."
    ),
    requires_confirmation=True,
)
async def delete_node(db: Session, node_id: int) -> dict:
    from app.db import crud
    from app.marznode import operations

    db_node = crud.get_node_by_id(db, node_id)
    if not db_node:
        return {"error": f"Node {node_id} not found"}

    node_name = db_node.name
    try:
        crud.remove_node(db, db_node)
    except Exception as e:
        return {"error": f"Failed to delete node: {str(e)}"}
    db.close()

    try:
        await operations.remove_node(node_id)
    except Exception as e:
        logger.warning("Node %s removed from DB but detach failed: %s", node_id, e)

    return {"success": True, "message": f"Node '{node_name}' (id={node_id}) deleted"}


@register_tool(
    name="clone_node_config",
    description=(
        "Copy backend config (e.g. Xray JSON) from a source node onto a target node "
        "and restart the target's backend. Useful when bringing a new node online "
        "with the same profile as an existing one. Both nodes must be connected. "
        "This will override the current config on the target — confirm before running."
    ),
    requires_confirmation=True,
)
async def clone_node_config(
    db: Session, source_node_id: int, target_node_id: int, backend: str = "xray"
) -> dict:
    from app.marznode import node_registry
    db.close()

    if source_node_id == target_node_id:
        return {"error": "Source and target nodes must differ"}

    source = node_registry.get(source_node_id)
    if not source:
        return {"error": f"Source node {source_node_id} is not connected"}
    target = node_registry.get(target_node_id)
    if not target:
        return {"error": f"Target node {target_node_id} is not connected"}

    try:
        config, config_format = await source.get_backend_config(name=backend)
    except Exception as e:
        return {"error": f"Failed to read config from source: {str(e)}"}

    try:
        await target.restart_backend(
            name=backend, config=config, config_format=int(config_format)
        )
    except Exception as e:
        return {"error": f"Failed to apply config on target: {str(e)}"}

    return {
        "success": True,
        "message": (
            f"Config of backend '{backend}' copied from node {source_node_id} "
            f"to node {target_node_id} and restarted"
        ),
        "config_size": len(config) if config else 0,
    }
