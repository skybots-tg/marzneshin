import asyncio
import logging
from typing import Annotated

import sqlalchemy
from fastapi import APIRouter, Body, Query
from fastapi import HTTPException, WebSocket
from fastapi_pagination.ext.sqlalchemy import paginate
from fastapi_pagination.links import Page
from starlette.websockets import WebSocketDisconnect, WebSocketState
from starlette.responses import StreamingResponse
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
async def resync_node_users(node_id: int, db: DBDep, admin: SudoAdminDep):
    """
    Force resync all users with the specified node.
    
    This will repopulate all users on the node, ensuring the node has
    up-to-date user data including device limits and allowed fingerprints.
    """
    db_node = crud.get_node_by_id(db, node_id)
    if not db_node:
        raise HTTPException(status_code=404, detail="Node not found")

    node = marznode.nodes.get(node_id)
    if not node:
        raise HTTPException(status_code=503, detail="Node is not connected")
    
    if not node.synced:
        raise HTTPException(status_code=503, detail="Node is not synced")

    try:
        await node.resync_users()
    except Exception as e:
        logger.error(f"Failed to resync users on node {node_id}: {e}")
        raise HTTPException(status_code=502, detail="Failed to resync users with node")

    logger.info(f"Users resynced on node `%s`", db_node.name)
    return {"status": "ok", "message": f"Users resynced on node {db_node.name}"}


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


@router.get("/{node_id}/migrate")
async def migrate_node(
    node_id: int,
    db: DBDep,
    ssh_user: str = Query("root"),
    ssh_port: int = Query(22),
    ssh_password: str = Query(None),
    ssh_key: str = Query(None),
    token: str = Query(None),
):
    """
    Migrate a node to the skybots-tg/marznode fork using Server-Sent Events (SSE).
    
    This endpoint streams migration progress in real-time using SSE format.
    Each event contains JSON data with the migration status and logs.
    Uses paramiko for SSH connections (no system ssh/sshpass required).
    """
    import json
    import paramiko
    import io
    import os
    
    # Authenticate using token from query parameter (EventSource doesn't support custom headers)
    if token:
        admin = get_admin(db, token)
        if not admin or not admin.is_sudo:
            raise HTTPException(status_code=403, detail="Unauthorized")
    else:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    db_node = crud.get_node_by_id(db, node_id)
    if not db_node:
        raise HTTPException(status_code=404, detail="Node not found")
    
    # Read migration script content
    script_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "migrate_skybots.sh")
    try:
        with open(script_path, "r") as f:
            migration_script = f.read()
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="Migration script not found")
    
    async def event_generator():
        """Generate SSE events for migration progress"""
        
        def send_event(event_type: str, data: dict):
            """Format and return SSE event"""
            json_data = json.dumps(data, ensure_ascii=False)
            return f"event: {event_type}\ndata: {json_data}\n\n"

        # Send initial connection message
        yield send_event("log", {
            "message": "Connection established, starting migration..."
        })
        
        migration_steps = [
            {"id": "step0", "name": "Step 0/9: Uploading SSL certificate to node", "status": "pending"},
            {"id": "step1", "name": "Step 1/9: Stopping and removing old containers with volumes", "status": "pending"},
            {"id": "step2", "name": "Step 2/9: Removing old docker image", "status": "pending"},
            {"id": "step3", "name": "Step 3/9: Creating backup of old installation", "status": "pending"},
            {"id": "step4", "name": "Step 4/9: Cloning skybots-tg/marznode fork", "status": "pending"},
            {"id": "step5", "name": "Step 5/9: Building docker image from source", "status": "pending"},
            {"id": "step6", "name": "Step 6/9: Updating compose.yml with new image", "status": "pending"},
            {"id": "step7", "name": "Step 7/9: Starting marznode with new configuration", "status": "pending"},
            {"id": "step8", "name": "Step 8/9: Verifying deployment", "status": "pending"},
        ]
        
        # Get TLS certificate from database
        tls_certificate = get_tls_certificate(db)
        
        ssh_client = None
        
        try:
            # Send initial steps
            yield send_event("steps", {
                "steps": migration_steps
            })
            
            yield send_event("log", {
                "message": f"Connecting to {db_node.address}:{ssh_port} as {ssh_user}..."
            })
            
            # Create SSH client
            ssh_client = paramiko.SSHClient()
            ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            # Connect using password or key
            connect_kwargs = {
                "hostname": db_node.address,
                "port": ssh_port,
                "username": ssh_user,
                "timeout": 30,
                "allow_agent": False,
                "look_for_keys": False,
            }
            
            if ssh_password:
                connect_kwargs["password"] = ssh_password
            elif ssh_key:
                # ssh_key can be a path or the key content itself
                if os.path.exists(ssh_key):
                    connect_kwargs["key_filename"] = ssh_key
                else:
                    # Assume it's the key content
                    key_file = io.StringIO(ssh_key)
                    try:
                        pkey = paramiko.RSAKey.from_private_key(key_file)
                    except:
                        key_file.seek(0)
                        try:
                            pkey = paramiko.Ed25519Key.from_private_key(key_file)
                        except:
                            key_file.seek(0)
                            pkey = paramiko.ECDSAKey.from_private_key(key_file)
                    connect_kwargs["pkey"] = pkey
            else:
                yield send_event("error", {
                    "message": "Either SSH password or SSH key is required"
                })
                return
            
            try:
                ssh_client.connect(**connect_kwargs)
            except paramiko.AuthenticationException:
                yield send_event("error", {
                    "message": "SSH authentication failed. Check your credentials."
                })
                return
            except paramiko.SSHException as e:
                yield send_event("error", {
                    "message": f"SSH connection error: {str(e)}"
                })
                return
            except Exception as e:
                yield send_event("error", {
                    "message": f"Connection failed: {str(e)}"
                })
                return
            
            yield send_event("log", {
                "message": "SSH connection established successfully"
            })
            
            # Step 0: Upload SSL certificate to node
            migration_steps[0]["status"] = "in_progress"
            yield send_event("step_update", {"step": migration_steps[0]})
            yield send_event("log", {
                "message": "Uploading SSL certificate to node..."
            })
            
            try:
                sftp = ssh_client.open_sftp()
                
                # Upload certificate to /opt/marznode/client.pem
                cert_content = tls_certificate.certificate.encode('utf-8')
                cert_file = io.BytesIO(cert_content)
                sftp.putfo(cert_file, "/opt/marznode/client.pem")
                sftp.chmod("/opt/marznode/client.pem", 0o600)
                
                yield send_event("log", {
                    "message": "✓ SSL certificate uploaded to /opt/marznode/client.pem"
                })
                migration_steps[0]["status"] = "success"
                yield send_event("step_update", {"step": migration_steps[0]})
                
                sftp.close()
            except Exception as e:
                yield send_event("log", {
                    "message": f"! Warning: Could not upload certificate: {str(e)} (will continue with migration)"
                })
                migration_steps[0]["status"] = "warning"
                yield send_event("step_update", {"step": migration_steps[0]})
            
            # Upload migration script via SFTP
            yield send_event("log", {
                "message": "Uploading migration script to node..."
            })
            
            try:
                sftp = ssh_client.open_sftp()
                script_file = io.BytesIO(migration_script.encode('utf-8'))
                sftp.putfo(script_file, "/tmp/migrate_skybots.sh")
                sftp.chmod("/tmp/migrate_skybots.sh", 0o755)
                sftp.close()
            except Exception as e:
                yield send_event("error", {
                    "message": f"Failed to upload migration script: {str(e)}"
                })
                return
            
            yield send_event("log", {
                "message": "Migration script uploaded, starting execution..."
            })
            
            # Execute migration script with real-time output
            transport = ssh_client.get_transport()
            channel = transport.open_session()
            channel.set_combine_stderr(True)
            channel.exec_command("bash /tmp/migrate_skybots.sh")
            
            step_index = -1
            
            # Read output in real-time
            buffer = ""
            while True:
                # Check if there's data to read
                if channel.recv_ready():
                    chunk = channel.recv(4096).decode('utf-8', errors='replace')
                    buffer += chunk
                    
                    # Process complete lines
                    while '\n' in buffer:
                        line, buffer = buffer.split('\n', 1)
                        line = line.strip()
                        if not line:
                            continue
                        
                        # Send log message
                        yield send_event("log", {
                            "message": line
                        })
                        
                        # Update step status based on log patterns
                        # Note: step 0 is certificate upload (handled above), bash script steps start at index 1
                        if "[Step 1/8]" in line:
                            step_index = 1
                            migration_steps[1]["status"] = "in_progress"
                            yield send_event("step_update", {"step": migration_steps[1]})
                        elif step_index == 1 and ("✓ Old containers stopped" in line or "! No compose file found" in line):
                            migration_steps[1]["status"] = "success"
                            yield send_event("step_update", {"step": migration_steps[1]})
                        elif "[Step 2/8]" in line:
                            step_index = 2
                            migration_steps[2]["status"] = "in_progress"
                            yield send_event("step_update", {"step": migration_steps[2]})
                        elif step_index == 2 and ("✓ Old image removed" in line or "! Old image not found" in line):
                            migration_steps[2]["status"] = "success"
                            yield send_event("step_update", {"step": migration_steps[2]})
                        elif "[Step 3/8]" in line:
                            step_index = 3
                            migration_steps[3]["status"] = "in_progress"
                            yield send_event("step_update", {"step": migration_steps[3]})
                        elif step_index == 3 and "✓ Backup created" in line:
                            migration_steps[3]["status"] = "success"
                            yield send_event("step_update", {"step": migration_steps[3]})
                        elif "[Step 4/8]" in line:
                            step_index = 4
                            migration_steps[4]["status"] = "in_progress"
                            yield send_event("step_update", {"step": migration_steps[4]})
                        elif step_index == 4 and "✓ Repository cloned successfully" in line:
                            migration_steps[4]["status"] = "success"
                            yield send_event("step_update", {"step": migration_steps[4]})
                        elif step_index == 4 and "✗ Failed to clone" in line:
                            migration_steps[4]["status"] = "error"
                            yield send_event("step_update", {"step": migration_steps[4]})
                        elif "[Step 5/8]" in line:
                            step_index = 5
                            migration_steps[5]["status"] = "in_progress"
                            yield send_event("step_update", {"step": migration_steps[5]})
                        elif step_index == 5 and "✓ Docker image built successfully" in line:
                            migration_steps[5]["status"] = "success"
                            yield send_event("step_update", {"step": migration_steps[5]})
                        elif "[Step 6/8]" in line:
                            step_index = 6
                            migration_steps[6]["status"] = "in_progress"
                            yield send_event("step_update", {"step": migration_steps[6]})
                        elif step_index == 6 and "✓ compose.yml updated" in line:
                            migration_steps[6]["status"] = "success"
                            yield send_event("step_update", {"step": migration_steps[6]})
                        elif "[Step 7/8]" in line:
                            step_index = 7
                            migration_steps[7]["status"] = "in_progress"
                            yield send_event("step_update", {"step": migration_steps[7]})
                        elif step_index == 7 and "✓ Services started successfully" in line:
                            migration_steps[7]["status"] = "success"
                            yield send_event("step_update", {"step": migration_steps[7]})
                        elif "[Step 8/8]" in line:
                            step_index = 8
                            migration_steps[8]["status"] = "in_progress"
                            yield send_event("step_update", {"step": migration_steps[8]})
                        elif step_index == 8 and "MIGRATION COMPLETED SUCCESSFULLY" in line:
                            migration_steps[8]["status"] = "success"
                            yield send_event("step_update", {"step": migration_steps[8]})
                        
                        # Check for errors
                        if "ERROR:" in line or "✗" in line:
                            if 0 <= step_index < len(migration_steps):
                                migration_steps[step_index]["status"] = "error"
                                yield send_event("step_update", {"step": migration_steps[step_index]})
                
                # Check if channel is closed
                if channel.exit_status_ready():
                    # Read any remaining data
                    while channel.recv_ready():
                        chunk = channel.recv(4096).decode('utf-8', errors='replace')
                        buffer += chunk
                    
                    # Process remaining buffer
                    for line in buffer.split('\n'):
                        line = line.strip()
                        if line:
                            yield send_event("log", {"message": line})
                    break
                
                # Small delay to prevent busy waiting
                await asyncio.sleep(0.1)
            
            exit_status = channel.recv_exit_status()
            
            # Send completion message
            if exit_status == 0:
                yield send_event("complete", {
                    "success": True,
                    "message": "Migration completed successfully"
                })
            else:
                yield send_event("complete", {
                    "success": False,
                    "message": f"Migration failed with exit code {exit_status}"
                })
                
        except Exception as e:
            logger.error(f"Migration error: {str(e)}", exc_info=True)
            yield send_event("error", {
                "message": f"Migration error: {str(e)}"
            })
            yield send_event("complete", {
                "success": False,
                "message": f"Migration failed: {str(e)}"
            })
        finally:
            if ssh_client:
                ssh_client.close()
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
    )
