import asyncio
import logging
from typing import Annotated

import sqlalchemy
from fastapi import APIRouter, Body, Query
from fastapi import HTTPException, WebSocket
from fastapi_pagination.ext.sqlalchemy import paginate
from fastapi_pagination.links import Page
from starlette.websockets import WebSocketDisconnect, WebSocketState
from grpclib.exceptions import StreamTerminatedError, GRPCError

from app import marznode
from app.db import crud, get_tls_certificate
from app.db.models import Node
from app.dependencies import (
    DBDep,
    SudoAdminDep,
    EndDateDep,
    StartDateDep,
    get_admin,
)
from app.models.node import (
    NodeCreate,
    NodeModify,
    NodeResponse,
    NodeSettings,
    NodeStatus,
    BackendConfig,
    BackendStats,
)
from app.models.system import TrafficUsageSeries

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/nodes", tags=["Node"])


@router.get("", response_model=Page[NodeResponse])
def get_nodes(
    db: DBDep,
    admin: SudoAdminDep,
    status: list[NodeStatus] = Query(None),
    name: str = Query(None),
):
    query = db.query(Node)

    if name:
        query = query.filter(Node.name.ilike(f"%{name}%"))

    if status:
        query = query.filter(Node.status.in_(status))

    return paginate(db, query)


@router.post("", response_model=NodeResponse)
async def add_node(new_node: NodeCreate, db: DBDep, admin: SudoAdminDep):
    try:
        db_node = crud.create_node(db, new_node)
    except sqlalchemy.exc.IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409, detail=f'Node "{new_node.name}" already exists'
        )
    certificate = get_tls_certificate(db)

    await marznode.operations.add_node(db_node, certificate)

    logger.info("New node `%s` added", db_node.name)
    return db_node


@router.get("/settings", response_model=NodeSettings)
def get_node_settings(db: DBDep, admin: SudoAdminDep):
    tls = crud.get_tls_certificate(db)

    return NodeSettings(certificate=tls.certificate)


@router.get("/{node_id}", response_model=NodeResponse)
def get_node(node_id: int, db: DBDep, admin: SudoAdminDep):
    db_node = crud.get_node_by_id(db, node_id)
    if not db_node:
        raise HTTPException(status_code=404, detail="Node not found")

    return db_node


@router.websocket("/{node_id}/{backend}/logs")
async def node_logs(
    node_id: int,
    backend: str,
    websocket: WebSocket,
    db: DBDep,
    include_buffer: bool = True,
):
    token = websocket.query_params.get("token", "") or websocket.headers.get(
        "Authorization", ""
    ).removeprefix("Bearer ")
    admin = get_admin(db, token)

    if not admin or not admin.is_sudo:
        return await websocket.close(reason="You're not allowed", code=4403)

    if not marznode.nodes.get(node_id):
        return await websocket.close(reason="Node not found", code=4404)

    await websocket.accept()
    try:
        async for line in marznode.nodes[node_id].get_logs(
            name=backend, include_buffer=include_buffer
        ):
            await websocket.send_text(line)
    except WebSocketDisconnect:
        logger.debug("websocket disconnected")
    except (StreamTerminatedError, GRPCError):
        logger.info("node %i detached", node_id)
    finally:
        if websocket.state == WebSocketState.CONNECTED:
            await websocket.close()


@router.put("/{node_id}", response_model=NodeResponse)
async def modify_node(
    node_id: int, modified_node: NodeModify, db: DBDep, admin: SudoAdminDep
):
    db_node = crud.get_node_by_id(db, node_id)
    if not db_node:
        raise HTTPException(status_code=404, detail="Node not found")

    db_node = crud.update_node(db, db_node, modified_node)

    await marznode.operations.remove_node(db_node.id)
    if db_node.status != NodeStatus.disabled:
        certificate = get_tls_certificate(db)
        await marznode.operations.add_node(db_node, certificate)

    logger.info("Node `%s` modified", db_node.name)
    return db_node


@router.delete("/{node_id}")
async def remove_node(node_id: int, db: DBDep, admin: SudoAdminDep):
    db_node = crud.get_node_by_id(db, node_id)
    if not db_node:
        raise HTTPException(status_code=404, detail="Node not found")

    crud.remove_node(db, db_node)
    await marznode.operations.remove_node(db_node.id)

    logger.info(f"Node `%s` deleted", db_node.name)
    return {}


@router.post("/{node_id}/resync")
async def reconnect_node(node_id: int, db: DBDep, admin: SudoAdminDep):
    db_node = crud.get_node_by_id(db, node_id)
    if not db_node:
        raise HTTPException(status_code=404, detail="Node not found")

    return {}


@router.get("/{node_id}/usage", response_model=TrafficUsageSeries)
def get_usage(
    node_id: int,
    db: DBDep,
    admin: SudoAdminDep,
    start_date: StartDateDep,
    end_date: EndDateDep,
):
    """
    Get nodes usage
    """
    node = crud.get_node_by_id(db, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    return crud.get_node_usage(db, start_date, end_date, node)


@router.get("/{node_id}/{backend}/stats", response_model=BackendStats)
async def get_backend_stats(
    node_id: int, backend: str, db: DBDep, admin: SudoAdminDep
):
    if not (node := marznode.nodes.get(node_id)):
        raise HTTPException(status_code=404, detail="Node not found")

    try:
        stats = await node.get_backend_stats(backend)
    except Exception:
        raise HTTPException(502)
    else:
        return BackendStats(running=stats.running)


@router.get("/{node_id}/{backend}/config", response_model=BackendConfig)
async def get_node_xray_config(
    node_id: int, backend: str, admin: SudoAdminDep
):
    if not (node := marznode.nodes.get(node_id)):
        raise HTTPException(status_code=404, detail="Node not found")

    try:
        config, config_format = await node.get_backend_config(name=backend)
    except Exception:
        raise HTTPException(status_code=502, detail="Node isn't responsive")
    else:
        return {"config": config, "format": config_format}


@router.put("/{node_id}/{backend}/config")
async def alter_node_xray_config(
    node_id: int,
    backend: str,
    admin: SudoAdminDep,
    config: Annotated[BackendConfig, Body()],
):
    if not (node := marznode.nodes.get(node_id)):
        raise HTTPException(status_code=404, detail="Node not found")

    try:
        await asyncio.wait_for(
            node.restart_backend(
                name=backend,
                config=config.config,
                config_format=config.format.value,
            ),
            5,
        )
    except:
        raise HTTPException(
            status_code=502, detail="No response from the node."
        )
    return {}


@router.websocket("/{node_id}/migrate")
async def migrate_node(
    node_id: int,
    websocket: WebSocket,
    db: DBDep,
):
    import subprocess
    import json
    
    token = websocket.query_params.get("token", "") or websocket.headers.get(
        "Authorization", ""
    ).removeprefix("Bearer ")
    admin = get_admin(db, token)

    if not admin or not admin.is_sudo:
        return await websocket.close(reason="You're not allowed", code=4403)

    db_node = crud.get_node_by_id(db, node_id)
    if not db_node:
        return await websocket.close(reason="Node not found", code=4404)

    await websocket.accept()
    
    migration_steps = [
        {"id": "check_root", "name": "Checking root privileges", "status": "pending"},
        {"id": "detect_compose", "name": "Detecting Docker Compose", "status": "pending"},
        {"id": "lock", "name": "Acquiring lock", "status": "pending"},
        {"id": "workdir", "name": "Checking working directory", "status": "pending"},
        {"id": "backup", "name": "Backing up files", "status": "pending"},
        {"id": "compose_check", "name": "Checking compose configuration", "status": "pending"},
        {"id": "git_update", "name": "Updating git repository", "status": "pending"},
        {"id": "compose_restart", "name": "Restarting services", "status": "pending"},
        {"id": "health_check", "name": "Running health check", "status": "pending"},
    ]
    
    try:
        # Send initial steps
        await websocket.send_json({
            "type": "steps",
            "steps": migration_steps
        })
        
        # Prepare SSH command to run migration script
        ssh_user = websocket.query_params.get("ssh_user", "root")
        ssh_port = websocket.query_params.get("ssh_port", "22")
        ssh_key = websocket.query_params.get("ssh_key", "")
        
        # Build SSH command
        ssh_cmd = [
            "ssh",
            "-p", ssh_port,
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null"
        ]
        
        if ssh_key:
            ssh_cmd.extend(["-i", ssh_key])
            
        ssh_cmd.append(f"{ssh_user}@{db_node.address}")
        
        # Check if script exists on remote, if not upload it
        check_script = "test -f /tmp/migrate_skybots.sh && echo 'exists' || echo 'missing'"
        check_proc = subprocess.Popen(
            ssh_cmd + [check_script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        check_output, _ = check_proc.communicate()
        
        if "missing" in check_output:
            # Upload script
            await websocket.send_json({
                "type": "log",
                "message": "Uploading migration script to node..."
            })
            
            script_path = "/app/../migrate_skybots.sh"
            scp_cmd = ["scp", "-P", ssh_port]
            if ssh_key:
                scp_cmd.extend(["-i", ssh_key])
            scp_cmd.extend([
                "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=/dev/null",
                script_path,
                f"{ssh_user}@{db_node.address}:/tmp/migrate_skybots.sh"
            ])
            
            scp_proc = subprocess.Popen(scp_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            await scp_proc.wait()
        
        # Execute migration script
        migration_cmd = ssh_cmd + ["bash /tmp/migrate_skybots.sh"]
        
        await websocket.send_json({
            "type": "log",
            "message": "Starting migration process..."
        })
        
        process = await asyncio.create_subprocess_exec(
            *migration_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            text=True
        )
        
        step_index = 0
        
        # Read output line by line
        while True:
            line = await process.stdout.readline()
            if not line:
                break
                
            line = line.strip()
            if not line:
                continue
            
            # Send log message
            await websocket.send_json({
                "type": "log",
                "message": line
            })
            
            # Update step status based on log patterns
            if "need_root" in line or "Run as root" in line:
                if step_index < len(migration_steps):
                    migration_steps[0]["status"] = "success" if "ERROR" not in line else "error"
                    await websocket.send_json({
                        "type": "step_update",
                        "step": migration_steps[0]
                    })
                    if "ERROR" in line:
                        step_index = 0
                    else:
                        step_index = 1
                        
            elif "detect_compose" in line or "docker compose" in line.lower():
                if step_index >= 1 and step_index < len(migration_steps):
                    migration_steps[1]["status"] = "success" if "ERROR" not in line else "error"
                    await websocket.send_json({
                        "type": "step_update",
                        "step": migration_steps[1]
                    })
                    if "ERROR" not in line:
                        step_index = 2
                        
            elif "lock" in line.lower() or "Another update" in line:
                if step_index >= 2 and step_index < len(migration_steps):
                    migration_steps[2]["status"] = "success" if "ERROR" not in line else "error"
                    await websocket.send_json({
                        "type": "step_update",
                        "step": migration_steps[2]
                    })
                    if "ERROR" not in line:
                        step_index = 3
                        
            elif "WORKDIR" in line or "ensure_workdir" in line:
                if step_index >= 3 and step_index < len(migration_steps):
                    migration_steps[3]["status"] = "success" if "ERROR" not in line else "error"
                    await websocket.send_json({
                        "type": "step_update",
                        "step": migration_steps[3]
                    })
                    if "ERROR" not in line:
                        step_index = 4
                        
            elif "Backup" in line or "backup" in line:
                if step_index >= 4 and step_index < len(migration_steps):
                    migration_steps[4]["status"] = "success" if "ERROR" not in line else "error"
                    await websocket.send_json({
                        "type": "step_update",
                        "step": migration_steps[4]
                    })
                    if "ERROR" not in line:
                        step_index = 5
                        
            elif "Compose:" in line and ("detected" in line or "validating" in line):
                if step_index >= 5 and step_index < len(migration_steps):
                    migration_steps[5]["status"] = "success" if "ERROR" not in line else "error"
                    await websocket.send_json({
                        "type": "step_update",
                        "step": migration_steps[5]
                    })
                    if "ERROR" not in line:
                        step_index = 6
                        
            elif "Git:" in line:
                if step_index >= 6 and step_index < len(migration_steps):
                    migration_steps[6]["status"] = "in_progress"
                    await websocket.send_json({
                        "type": "step_update",
                        "step": migration_steps[6]
                    })
                if "hard reset" in line.lower() or "cleaning" in line.lower():
                    migration_steps[6]["status"] = "success" if "ERROR" not in line else "error"
                    await websocket.send_json({
                        "type": "step_update",
                        "step": migration_steps[6]
                    })
                    if "ERROR" not in line:
                        step_index = 7
                        
            elif "Compose:" in line and ("up" in line or "applying" in line or "recreate" in line):
                if step_index >= 7 and step_index < len(migration_steps):
                    migration_steps[7]["status"] = "in_progress"
                    await websocket.send_json({
                        "type": "step_update",
                        "step": migration_steps[7]
                    })
            elif "Compose: status" in line:
                if step_index >= 7 and step_index < len(migration_steps):
                    migration_steps[7]["status"] = "success"
                    await websocket.send_json({
                        "type": "step_update",
                        "step": migration_steps[7]
                    })
                    step_index = 8
                    
            elif "Docker:" in line or "health" in line.lower():
                if step_index >= 8 and step_index < len(migration_steps):
                    migration_steps[8]["status"] = "success" if "ERROR" not in line else "error"
                    await websocket.send_json({
                        "type": "step_update",
                        "step": migration_steps[8]
                    })
                    
            elif "update done" in line.lower():
                # Mark all remaining steps as success
                for i in range(step_index, len(migration_steps)):
                    if migration_steps[i]["status"] == "pending":
                        migration_steps[i]["status"] = "success"
                        await websocket.send_json({
                            "type": "step_update",
                            "step": migration_steps[i]
                        })
        
        await process.wait()
        
        # Send completion message
        if process.returncode == 0:
            await websocket.send_json({
                "type": "complete",
                "success": True,
                "message": "Migration completed successfully"
            })
        else:
            await websocket.send_json({
                "type": "complete",
                "success": False,
                "message": f"Migration failed with exit code {process.returncode}"
            })
            
    except WebSocketDisconnect:
        logger.debug("websocket disconnected during migration")
    except Exception as e:
        logger.error(f"Migration error: {str(e)}")
        try:
            await websocket.send_json({
                "type": "error",
                "message": str(e)
            })
        except:
            pass
    finally:
        if websocket.state == WebSocketState.CONNECTED:
            await websocket.close()
