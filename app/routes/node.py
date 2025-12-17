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
    DeviceInfo,
    UserDevicesResponse,
    AllUsersDevicesResponse,
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


@router.get("/{node_id}/devices/{user_id}", response_model=UserDevicesResponse)
async def get_user_devices(
    node_id: int,
    user_id: int,
    active_only: bool = Query(False, description="Return only active devices"),
    admin: SudoAdminDep = None,
):
    """
    Get device history for a specific user on a node.
    
    This endpoint fetches the device connection history from the node's internal storage.
    Each device is identified by a unique combination of IP address and client name.
    
    - **node_id**: ID of the node to query
    - **user_id**: ID of the user whose devices to fetch
    - **active_only**: If True, return only devices active in the last 5 minutes
    
    Returns device information including:
    - Connection times (first_seen, last_seen)
    - Traffic statistics (upload, download, total)
    - Device metadata (IP, client name, user agent, protocol, TLS fingerprint)
    - Activity status
    """
    if not (node := marznode.nodes.get(node_id)):
        raise HTTPException(status_code=404, detail="Node not found")

    try:
        response = await node.fetch_user_devices(uid=user_id, active_only=active_only)
    except Exception as e:
        logger.error(f"Failed to fetch user devices from node {node_id}: {e}")
        raise HTTPException(
            status_code=502, 
            detail="Failed to fetch device history from node"
        )

    # Convert protobuf response to Pydantic model
    devices = [
        DeviceInfo(
            remote_ip=device.remote_ip,
            client_name=device.client_name,
            user_agent=device.user_agent if device.user_agent else None,
            protocol=device.protocol if device.protocol else None,
            tls_fingerprint=device.tls_fingerprint if device.tls_fingerprint else None,
            first_seen=device.first_seen,
            last_seen=device.last_seen,
            total_usage=device.total_usage,
            uplink=device.uplink,
            downlink=device.downlink,
            is_active=device.is_active,
        )
        for device in response.devices
    ]

    return UserDevicesResponse(uid=response.uid, devices=devices)


@router.get("/{node_id}/devices", response_model=AllUsersDevicesResponse)
async def get_all_devices(
    node_id: int,
    admin: SudoAdminDep = None,
):
    """
    Get device history for all users on a node.
    
    This endpoint fetches the complete device connection history from the node's 
    internal storage for all users.
    
    - **node_id**: ID of the node to query
    
    Returns a list of users with their device information.
    
    **Note**: This endpoint can return a large amount of data. Consider using
    pagination or filtering by user_id for production use.
    """
    if not (node := marznode.nodes.get(node_id)):
        raise HTTPException(status_code=404, detail="Node not found")

    try:
        response = await node.fetch_all_devices()
    except Exception as e:
        logger.error(f"Failed to fetch all devices from node {node_id}: {e}")
        raise HTTPException(
            status_code=502,
            detail="Failed to fetch device history from node"
        )

    # Convert protobuf response to Pydantic model
    users = []
    for user_devices in response.users:
        devices = [
            DeviceInfo(
                remote_ip=device.remote_ip,
                client_name=device.client_name,
                user_agent=device.user_agent if device.user_agent else None,
                protocol=device.protocol if device.protocol else None,
                tls_fingerprint=device.tls_fingerprint if device.tls_fingerprint else None,
                first_seen=device.first_seen,
                last_seen=device.last_seen,
                total_usage=device.total_usage,
                uplink=device.uplink,
                downlink=device.downlink,
                is_active=device.is_active,
            )
            for device in user_devices.devices
        ]
        users.append(UserDevicesResponse(uid=user_devices.uid, devices=devices))

    return AllUsersDevicesResponse(users=users)


@router.websocket("/{node_id}/migrate")
async def migrate_node(
    node_id: int,
    websocket: WebSocket,
    db: DBDep,
):
    import subprocess
    import json
    import shutil
    
    token = websocket.query_params.get("token", "") or websocket.headers.get(
        "Authorization", ""
    ).removeprefix("Bearer ")
    admin = get_admin(db, token)

    if not admin or not admin.is_sudo:
        return await websocket.close(reason="You're not allowed", code=4403)

    db_node = crud.get_node_by_id(db, node_id)
    if not db_node:
        return await websocket.close(reason="Node not found", code=4404)

    try:
        await websocket.accept()
        
        # Send initial connection message
        await websocket.send_json({
            "type": "log",
            "message": "WebSocket connection established"
        })
        
    except Exception as e:
        logger.error(f"Failed to accept WebSocket: {e}")
        return
    
    migration_steps = [
        {"id": "step1", "name": "Step 1/8: Stopping and removing old containers with volumes", "status": "pending"},
        {"id": "step2", "name": "Step 2/8: Removing old docker image", "status": "pending"},
        {"id": "step3", "name": "Step 3/8: Creating backup of old installation", "status": "pending"},
        {"id": "step4", "name": "Step 4/8: Cloning skybots-tg/marznode fork", "status": "pending"},
        {"id": "step5", "name": "Step 5/8: Building docker image from source", "status": "pending"},
        {"id": "step6", "name": "Step 6/8: Updating compose.yml with new image", "status": "pending"},
        {"id": "step7", "name": "Step 7/8: Starting marznode with new configuration", "status": "pending"},
        {"id": "step8", "name": "Step 8/8: Verifying deployment", "status": "pending"},
    ]
    
    try:
        # Check if required tools are available
        ssh_password = websocket.query_params.get("ssh_password", "")
        
        if ssh_password and not shutil.which("sshpass"):
            await websocket.send_json({
                "type": "error",
                "message": "sshpass is not installed on the server. Please install it: apt-get install sshpass"
            })
            await websocket.close()
            return
            
        if not shutil.which("ssh"):
            await websocket.send_json({
                "type": "error",
                "message": "ssh is not installed on the server"
            })
            await websocket.close()
            return
        
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
        ssh_cmd = []
        scp_cmd_prefix = []
        
        if ssh_password:
            # Use sshpass for password authentication
            ssh_cmd = ["sshpass", "-p", ssh_password]
            scp_cmd_prefix = ["sshpass", "-p", ssh_password]
        
        ssh_cmd.extend([
            "ssh",
            "-p", ssh_port,
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null"
        ])
        
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
            scp_cmd = []
            
            if scp_cmd_prefix:
                scp_cmd.extend(scp_cmd_prefix)
                
            scp_cmd.extend(["scp", "-P", ssh_port])
            
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
        
        step_index = -1
        
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
            # Step 1: Stopping and removing containers
            if "[Step 1/8]" in line:
                step_index = 0
                migration_steps[0]["status"] = "in_progress"
                await websocket.send_json({
                    "type": "step_update",
                    "step": migration_steps[0]
                })
            elif step_index == 0 and ("✓ Old containers stopped" in line or "! No compose file found" in line):
                migration_steps[0]["status"] = "success"
                await websocket.send_json({
                    "type": "step_update",
                    "step": migration_steps[0]
                })
                        
            # Step 2: Removing old image
            elif "[Step 2/8]" in line:
                step_index = 1
                migration_steps[1]["status"] = "in_progress"
                await websocket.send_json({
                    "type": "step_update",
                    "step": migration_steps[1]
                })
            elif step_index == 1 and ("✓ Old image removed" in line or "! Old image not found" in line):
                migration_steps[1]["status"] = "success"
                await websocket.send_json({
                    "type": "step_update",
                    "step": migration_steps[1]
                })
                        
            # Step 3: Backup
            elif "[Step 3/8]" in line:
                step_index = 2
                migration_steps[2]["status"] = "in_progress"
                await websocket.send_json({
                    "type": "step_update",
                    "step": migration_steps[2]
                })
            elif step_index == 2 and "✓ Backup created" in line:
                migration_steps[2]["status"] = "success"
                await websocket.send_json({
                    "type": "step_update",
                    "step": migration_steps[2]
                })
                        
            # Step 4: Cloning repository
            elif "[Step 4/8]" in line:
                step_index = 3
                migration_steps[3]["status"] = "in_progress"
                await websocket.send_json({
                    "type": "step_update",
                    "step": migration_steps[3]
                })
            elif step_index == 3 and "✓ Repository cloned successfully" in line:
                migration_steps[3]["status"] = "success"
                await websocket.send_json({
                    "type": "step_update",
                    "step": migration_steps[3]
                })
            elif step_index == 3 and "✗ Failed to clone" in line:
                migration_steps[3]["status"] = "error"
                await websocket.send_json({
                    "type": "step_update",
                    "step": migration_steps[3]
                })
                        
            # Step 5: Building image
            elif "[Step 5/8]" in line:
                step_index = 4
                migration_steps[4]["status"] = "in_progress"
                await websocket.send_json({
                    "type": "step_update",
                    "step": migration_steps[4]
                })
            elif step_index == 4 and "✓ Docker image built successfully" in line:
                migration_steps[4]["status"] = "success"
                await websocket.send_json({
                    "type": "step_update",
                    "step": migration_steps[4]
                })
                        
            # Step 6: Updating compose
            elif "[Step 6/8]" in line:
                step_index = 5
                migration_steps[5]["status"] = "in_progress"
                await websocket.send_json({
                    "type": "step_update",
                    "step": migration_steps[5]
                })
            elif step_index == 5 and "✓ compose.yml updated" in line:
                migration_steps[5]["status"] = "success"
                await websocket.send_json({
                    "type": "step_update",
                    "step": migration_steps[5]
                })
                        
            # Step 7: Starting services
            elif "[Step 7/8]" in line:
                step_index = 6
                migration_steps[6]["status"] = "in_progress"
                await websocket.send_json({
                    "type": "step_update",
                    "step": migration_steps[6]
                })
            elif step_index == 6 and "✓ Services started successfully" in line:
                migration_steps[6]["status"] = "success"
                await websocket.send_json({
                    "type": "step_update",
                    "step": migration_steps[6]
                })
                    
            # Step 8: Verification
            elif "[Step 8/8]" in line:
                step_index = 7
                migration_steps[7]["status"] = "in_progress"
                await websocket.send_json({
                    "type": "step_update",
                    "step": migration_steps[7]
                })
            elif step_index == 7 and "MIGRATION COMPLETED SUCCESSFULLY" in line:
                migration_steps[7]["status"] = "success"
                await websocket.send_json({
                    "type": "step_update",
                    "step": migration_steps[7]
                })
                    
            # Check for errors
            if "ERROR:" in line or "✗" in line:
                if 0 <= step_index < len(migration_steps):
                    migration_steps[step_index]["status"] = "error"
                    await websocket.send_json({
                        "type": "step_update",
                        "step": migration_steps[step_index]
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
        logger.error(f"Migration error: {str(e)}", exc_info=True)
        try:
            if websocket.state == WebSocketState.CONNECTED:
                await websocket.send_json({
                    "type": "error",
                    "message": f"Migration error: {str(e)}"
                })
                await websocket.send_json({
                    "type": "complete",
                    "success": False,
                    "message": f"Migration failed: {str(e)}"
                })
        except Exception as send_err:
            logger.error(f"Failed to send error message: {send_err}")
    finally:
        if websocket.state == WebSocketState.CONNECTED:
            await websocket.close()
