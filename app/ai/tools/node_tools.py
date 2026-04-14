import logging

from sqlalchemy.orm import Session

from app.ai.tool_registry import register_tool

logger = logging.getLogger(__name__)


@register_tool(
    name="list_nodes",
    description="List all nodes with their statuses, addresses, and basic info",
    requires_confirmation=False,
)
async def list_nodes(db: Session) -> dict:
    from app.db.models import Node
    nodes = db.query(Node).all()
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
        "total": len(nodes),
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
    description="Get the live backend config (e.g. Xray JSON) of a specific node. Returns the raw config string.",
    requires_confirmation=False,
)
async def get_node_config(db: Session, node_id: int, backend: str = "xray") -> dict:
    from app.marznode import node_registry
    db.close()
    node = node_registry.get(node_id)
    if not node:
        return {"error": f"Node {node_id} is not connected"}
    try:
        config, config_format = await node.get_backend_config(name=backend)
        return {"config": config, "format": config_format}
    except Exception as e:
        return {"error": f"Failed to get config: {str(e)}"}


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
    name="get_node_filtering",
    description="Get filtering/adblock settings for a specific node",
    requires_confirmation=False,
)
async def get_node_filtering(db: Session, node_id: int) -> dict:
    from app.db import crud
    config = crud.get_filtering_config(db, node_id)
    if not config:
        return {"node_id": node_id, "configured": False}
    return {
        "node_id": node_id,
        "configured": True,
        "adblock_enabled": config.adblock_enabled,
        "adguard_installed": config.adguard_installed,
        "dns_provider": str(config.dns_provider) if config.dns_provider else None,
    }


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
    from app.db import crud, get_tls_certificate, GetDB
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
