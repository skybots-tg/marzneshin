import asyncio
import io
import json
import logging
import os

import paramiko
from fastapi import APIRouter, HTTPException
from starlette.responses import StreamingResponse

from app.db import crud
from app.dependencies import SudoAdminDep, DBDep
from app.models.node import SSHCredentials

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/nodes", tags=["Node"])


@router.post("/{node_id}/update-xray")
async def update_node_xray(
    node_id: int,
    credentials: SSHCredentials,
    admin: SudoAdminDep,
    db: DBDep,
):
    """
    Update Xray-core to the latest version on a node using Server-Sent Events (SSE).

    This endpoint connects via SSH, downloads the latest Xray binary from GitHub,
    mounts it into the marznode container, and restarts the service.
    """
    def _db_work():
        db_node = crud.get_node_by_id(db, node_id)
        if not db_node:
            raise HTTPException(status_code=404, detail="Node not found")
        node_address = db_node.address
        db.close()
        return node_address

    node_address = await asyncio.to_thread(_db_work)

    script_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "update_xray.sh")
    try:
        with open(script_path, "r") as f:
            update_script = f.read()
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="Update script not found")

    async def event_generator():
        """Generate SSE events for update progress"""

        def send_event(event_type: str, data: dict):
            """Format and return SSE event"""
            json_data = json.dumps(data, ensure_ascii=False)
            return f"event: {event_type}\ndata: {json_data}\n\n"

        yield send_event("log", {
            "message": "Connection established, starting Xray update..."
        })

        update_steps = [
            {"id": "step1", "name": "Detecting system architecture", "status": "pending"},
            {"id": "step2", "name": "Downloading latest Xray-core", "status": "pending"},
            {"id": "step3", "name": "Extracting Xray binary", "status": "pending"},
            {"id": "step4", "name": "Updating docker-compose and restarting marznode", "status": "pending"},
        ]

        ssh_client = None

        try:
            yield send_event("steps", {"steps": update_steps})

            yield send_event("log", {
                "message": f"Connecting to {node_address}:{credentials.ssh_port} as {credentials.ssh_user}..."
            })

            ssh_client = paramiko.SSHClient()
            ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            connect_kwargs = {
                "hostname": node_address,
                "port": credentials.ssh_port,
                "username": credentials.ssh_user,
                "timeout": 30,
                "allow_agent": False,
                "look_for_keys": False,
            }

            if credentials.ssh_password:
                connect_kwargs["password"] = credentials.ssh_password
            elif credentials.ssh_key:
                if os.path.exists(credentials.ssh_key):
                    connect_kwargs["key_filename"] = credentials.ssh_key
                else:
                    key_file = io.StringIO(credentials.ssh_key)
                    try:
                        pkey = paramiko.RSAKey.from_private_key(key_file)
                    except (paramiko.SSHException, ValueError):
                        key_file.seek(0)
                        try:
                            pkey = paramiko.Ed25519Key.from_private_key(key_file)
                        except (paramiko.SSHException, ValueError):
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

            yield send_event("log", {
                "message": "Uploading update script to node..."
            })

            try:
                sftp = ssh_client.open_sftp()
                script_file = io.BytesIO(update_script.encode('utf-8'))
                sftp.putfo(script_file, "/tmp/update_xray.sh")
                sftp.chmod("/tmp/update_xray.sh", 0o755)
                sftp.close()
            except Exception as e:
                yield send_event("error", {
                    "message": f"Failed to upload update script: {str(e)}"
                })
                return

            yield send_event("log", {
                "message": "Update script uploaded, starting execution..."
            })

            transport = ssh_client.get_transport()
            channel = transport.open_session()
            channel.set_combine_stderr(True)
            channel.exec_command("bash /tmp/update_xray.sh")

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

                        yield send_event("log", {"message": line})

                        if "[Step 1/4]" in line:
                            step_index = 0
                            update_steps[0]["status"] = "in_progress"
                            yield send_event("step_update", {"step": update_steps[0]})
                        elif step_index == 0 and "Architecture:" in line:
                            update_steps[0]["status"] = "success"
                            yield send_event("step_update", {"step": update_steps[0]})
                        elif "[Step 2/4]" in line:
                            step_index = 1
                            update_steps[1]["status"] = "in_progress"
                            yield send_event("step_update", {"step": update_steps[1]})
                        elif step_index == 1 and "Downloaded successfully" in line:
                            update_steps[1]["status"] = "success"
                            yield send_event("step_update", {"step": update_steps[1]})
                        elif "[Step 3/4]" in line:
                            step_index = 2
                            update_steps[2]["status"] = "in_progress"
                            yield send_event("step_update", {"step": update_steps[2]})
                        elif step_index == 2 and "installed successfully" in line:
                            update_steps[2]["status"] = "success"
                            yield send_event("step_update", {"step": update_steps[2]})
                        elif "[Step 4/4]" in line:
                            step_index = 3
                            update_steps[3]["status"] = "in_progress"
                            yield send_event("step_update", {"step": update_steps[3]})
                        elif step_index == 3 and ("Marznode restarted" in line or "ALREADY UP TO DATE" in line):
                            update_steps[3]["status"] = "success"
                            yield send_event("step_update", {"step": update_steps[3]})

                        if "✗" in line:
                            if 0 <= step_index < len(update_steps):
                                update_steps[step_index]["status"] = "error"
                                yield send_event("step_update", {"step": update_steps[step_index]})

                        if "ALREADY UP TO DATE" in line:
                            for s in update_steps:
                                if s["status"] == "pending":
                                    s["status"] = "success"
                                    yield send_event("step_update", {"step": s})

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
                    "message": "Xray update completed successfully"
                })
            else:
                yield send_event("complete", {
                    "success": False,
                    "message": f"Xray update failed with exit code {exit_status}"
                })

        except Exception as e:
            logger.error(f"Xray update error: {str(e)}", exc_info=True)
            yield send_event("error", {
                "message": f"Update error: {str(e)}"
            })
            yield send_event("complete", {
                "success": False,
                "message": f"Update failed: {str(e)}"
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
