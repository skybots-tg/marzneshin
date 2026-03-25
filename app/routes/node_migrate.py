import asyncio
import io
import json
import logging
import os

import paramiko
from fastapi import APIRouter, Query, HTTPException
from starlette.responses import StreamingResponse

from app.db import crud, get_tls_certificate, GetDB
from app.dependencies import get_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/nodes", tags=["Node"])


@router.get("/{node_id}/migrate")
async def migrate_node(
    node_id: int,
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
    with GetDB() as db:
        if token:
            admin = get_admin(db, token)
            if not admin or not admin.is_sudo:
                raise HTTPException(status_code=403, detail="Unauthorized")
        else:
            raise HTTPException(status_code=401, detail="Authentication required")

        db_node = crud.get_node_by_id(db, node_id)
        if not db_node:
            raise HTTPException(status_code=404, detail="Node not found")
        node_address = db_node.address

        tls_certificate = get_tls_certificate(db)

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

        ssh_client = None

        try:
            yield send_event("steps", {
                "steps": migration_steps
            })

            yield send_event("log", {
                "message": f"Connecting to {node_address}:{ssh_port} as {ssh_user}..."
            })

            ssh_client = paramiko.SSHClient()
            ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            connect_kwargs = {
                "hostname": node_address,
                "port": ssh_port,
                "username": ssh_user,
                "timeout": 30,
                "allow_agent": False,
                "look_for_keys": False,
            }

            if ssh_password:
                connect_kwargs["password"] = ssh_password
            elif ssh_key:
                if os.path.exists(ssh_key):
                    connect_kwargs["key_filename"] = ssh_key
                else:
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

            migration_steps[0]["status"] = "in_progress"
            yield send_event("step_update", {"step": migration_steps[0]})
            yield send_event("log", {
                "message": "Uploading SSL certificate to node..."
            })

            try:
                sftp = ssh_client.open_sftp()

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

            transport = ssh_client.get_transport()
            channel = transport.open_session()
            channel.set_combine_stderr(True)
            channel.exec_command("bash /tmp/migrate_skybots.sh")

            step_index = -1

            buffer = ""
            while True:
                if channel.recv_ready():
                    chunk = channel.recv(4096).decode('utf-8', errors='replace')
                    buffer += chunk

                    while '\n' in buffer:
                        line, buffer = buffer.split('\n', 1)
                        line = line.strip()
                        if not line:
                            continue

                        yield send_event("log", {
                            "message": line
                        })

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

                        if "ERROR:" in line or "✗" in line:
                            if 0 <= step_index < len(migration_steps):
                                migration_steps[step_index]["status"] = "error"
                                yield send_event("step_update", {"step": migration_steps[step_index]})

                if channel.exit_status_ready():
                    while channel.recv_ready():
                        chunk = channel.recv(4096).decode('utf-8', errors='replace')
                        buffer += chunk

                    for line in buffer.split('\n'):
                        line = line.strip()
                        if line:
                            yield send_event("log", {"message": line})
                    break

                await asyncio.sleep(0.1)

            exit_status = channel.recv_exit_status()

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
            "X-Accel-Buffering": "no",
        }
    )
