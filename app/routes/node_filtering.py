import asyncio
import io
import json
import logging
import os

import paramiko
from fastapi import APIRouter, HTTPException
from starlette.responses import StreamingResponse

from app import marznode
from app.config.db import get_secret_key
from app.db import crud
from app.dependencies import SudoAdminDep, DBDep
from app.models.node_filtering import (
    NodeFilteringConfigResponse,
    NodeFilteringConfigUpdate,
    SSHCredentialsStore,
    SSHCredentialsInfo,
    SSHCredentialsWithPin,
)
from app.utils.crypto import (
    encrypt_credentials,
    decrypt_credentials,
    verify_pin,
)
from app.utils.xray_config_patcher import patch_config_enable, patch_config_disable

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/nodes", tags=["Node Filtering"])


@router.get("/{node_id}/filtering", response_model=NodeFilteringConfigResponse)
def get_filtering(node_id: int, admin: SudoAdminDep, db: DBDep):
    node = crud.get_node_by_id(db, node_id)
    if not node:
        raise HTTPException(404, "Node not found")
    cfg = crud.get_or_create_filtering_config(db, node_id)
    return NodeFilteringConfigResponse.model_validate(cfg)


@router.put("/{node_id}/filtering", response_model=NodeFilteringConfigResponse)
async def update_filtering(
    node_id: int,
    update: NodeFilteringConfigUpdate,
    admin: SudoAdminDep,
    db: DBDep,
):
    node = crud.get_node_by_id(db, node_id)
    if not node:
        raise HTTPException(404, "Node not found")

    cfg = crud.update_filtering_config(db, node_id, update)

    marznode_ref = marznode.nodes.get(node_id)
    if not marznode_ref:
        return NodeFilteringConfigResponse.model_validate(cfg)

    backend_names = [b.name for b in node.backends]
    response = NodeFilteringConfigResponse.model_validate(cfg)
    db.close()

    for backend_name in backend_names:
        try:
            config_str, config_format = await marznode_ref.get_backend_config(
                name=backend_name
            )
        except Exception:
            logger.warning(
                "Could not fetch config for backend %s on node %d",
                backend_name,
                node_id,
            )
            continue

        if config_format != 1:
            continue

        try:
            if cfg.adblock_enabled:
                patched = patch_config_enable(
                    config_str,
                    cfg.dns_provider,
                    cfg.dns_address,
                    cfg.adguard_home_port,
                )
            else:
                patched = patch_config_disable(config_str)

            await asyncio.wait_for(
                marznode_ref.restart_backend(
                    name=backend_name,
                    config=patched,
                    config_format=config_format,
                ),
                timeout=60,
            )
            logger.info(
                "Patched backend '%s' on node %d (adblock=%s)",
                backend_name,
                node_id,
                cfg.adblock_enabled,
            )
        except Exception:
            logger.exception(
                "Failed to patch backend '%s' on node %d",
                backend_name,
                node_id,
            )

    return response


# --- SSH Credentials ---

@router.get("/{node_id}/ssh-credentials", response_model=SSHCredentialsInfo)
def get_ssh_creds_info(node_id: int, admin: SudoAdminDep, db: DBDep):
    node = crud.get_node_by_id(db, node_id)
    if not node:
        raise HTTPException(404, "Node not found")
    creds = crud.get_ssh_credentials(db, node_id)
    if creds is None:
        return SSHCredentialsInfo(exists=False)
    return SSHCredentialsInfo(exists=True)


@router.post("/{node_id}/ssh-credentials", response_model=SSHCredentialsInfo)
def store_ssh_creds(
    node_id: int,
    body: SSHCredentialsStore,
    admin: SudoAdminDep,
    db: DBDep,
):
    node = crud.get_node_by_id(db, node_id)
    if not node:
        raise HTTPException(404, "Node not found")
    if not body.ssh_password and not body.ssh_key:
        raise HTTPException(400, "Either ssh_password or ssh_key is required")

    pin_hash = crud.get_ssh_pin_hash(db)
    if not pin_hash:
        raise HTTPException(400, "Global SSH PIN is not configured. Set it in system settings first.")
    if not verify_pin(body.pin, pin_hash):
        raise HTTPException(403, "Invalid PIN")

    secret = get_secret_key()
    payload = {
        "ssh_user": body.ssh_user,
        "ssh_port": body.ssh_port,
        "ssh_password": body.ssh_password,
        "ssh_key": body.ssh_key,
    }
    encrypted_data, salt = encrypt_credentials(payload, body.pin, secret)
    crud.save_ssh_credentials(db, node_id, encrypted_data, salt)
    return SSHCredentialsInfo(
        exists=True, ssh_user=body.ssh_user, ssh_port=body.ssh_port
    )


@router.delete("/{node_id}/ssh-credentials")
def remove_ssh_creds(node_id: int, admin: SudoAdminDep, db: DBDep):
    node = crud.get_node_by_id(db, node_id)
    if not node:
        raise HTTPException(404, "Node not found")
    deleted = crud.delete_ssh_credentials(db, node_id)
    if not deleted:
        raise HTTPException(404, "No stored credentials found")
    return {"detail": "Credentials deleted"}


# --- Install AdGuard Home ---

@router.post("/{node_id}/install-adguard")
async def install_adguard(
    node_id: int,
    body: SSHCredentialsWithPin,
    admin: SudoAdminDep,
    db: DBDep,
):
    node = crud.get_node_by_id(db, node_id)
    if not node:
        raise HTTPException(404, "Node not found")

    creds_row = crud.get_ssh_credentials(db, node_id)
    if not creds_row:
        raise HTTPException(400, "No stored SSH credentials for this node")

    pin_hash = crud.get_ssh_pin_hash(db)
    if not pin_hash:
        raise HTTPException(400, "Global SSH PIN is not configured")
    if not verify_pin(body.pin, pin_hash):
        raise HTTPException(403, "Invalid PIN")

    secret = get_secret_key()
    try:
        creds = decrypt_credentials(
            creds_row.encrypted_data, creds_row.encryption_salt, body.pin, secret
        )
    except ValueError:
        raise HTTPException(403, "Decryption failed — invalid PIN")

    cfg = crud.get_or_create_filtering_config(db, node_id)
    adguard_port = cfg.adguard_home_port
    node_address = node.address
    db.close()

    script_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "install_adguard.sh",
    )
    try:
        with open(script_path, "r") as f:
            install_script = f.read()
    except FileNotFoundError:
        raise HTTPException(500, "Install script not found")

    async def event_generator():
        def send_event(event_type: str, data: dict):
            json_data = json.dumps(data, ensure_ascii=False)
            return f"event: {event_type}\ndata: {json_data}\n\n"

        steps = [
            {"id": "step1", "name": "Checking Docker installation", "status": "pending"},
            {"id": "step2", "name": "Creating configuration", "status": "pending"},
            {"id": "step3", "name": "Stopping old container", "status": "pending"},
            {"id": "step4", "name": "Starting AdGuard Home", "status": "pending"},
            {"id": "step5", "name": "Verifying installation", "status": "pending"},
        ]

        ssh_client = None
        try:
            yield send_event("steps", {"steps": steps})
            yield send_event("log", {
                "message": f"Connecting to {node_address}:{creds['ssh_port']} as {creds['ssh_user']}..."
            })

            ssh_client = paramiko.SSHClient()
            ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            connect_kwargs = {
                "hostname": node_address,
                "port": creds["ssh_port"],
                "username": creds["ssh_user"],
                "timeout": 30,
                "allow_agent": False,
                "look_for_keys": False,
            }

            if creds.get("ssh_password"):
                connect_kwargs["password"] = creds["ssh_password"]
            elif creds.get("ssh_key"):
                key_str = creds["ssh_key"]
                if os.path.exists(key_str):
                    connect_kwargs["key_filename"] = key_str
                else:
                    key_file = io.StringIO(key_str)
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
                yield send_event("error", {"message": "No SSH auth method in stored credentials"})
                return

            try:
                ssh_client.connect(**connect_kwargs)
            except paramiko.AuthenticationException:
                yield send_event("error", {"message": "SSH authentication failed"})
                return
            except Exception as e:
                yield send_event("error", {"message": f"Connection failed: {e}"})
                return

            yield send_event("log", {"message": "SSH connection established"})

            sftp = ssh_client.open_sftp()
            script_bytes = io.BytesIO(install_script.encode("utf-8"))
            sftp.putfo(script_bytes, "/tmp/install_adguard.sh")
            sftp.chmod("/tmp/install_adguard.sh", 0o755)
            sftp.close()

            yield send_event("log", {"message": "Install script uploaded, executing..."})

            transport = ssh_client.get_transport()
            channel = transport.open_session()
            channel.set_combine_stderr(True)
            channel.exec_command(f"bash /tmp/install_adguard.sh {adguard_port}")

            step_index = -1
            buffer = ""
            while True:
                if channel.recv_ready():
                    chunk = channel.recv(4096).decode("utf-8", errors="replace")
                    buffer += chunk

                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()
                        if not line:
                            continue

                        yield send_event("log", {"message": line})

                        for i in range(5):
                            marker = f"[Step {i+1}/5]"
                            if marker in line:
                                if 0 <= step_index < len(steps):
                                    steps[step_index]["status"] = "success"
                                    yield send_event("step_update", {"step": steps[step_index]})
                                step_index = i
                                steps[i]["status"] = "in_progress"
                                yield send_event("step_update", {"step": steps[i]})

                        if "installed successfully" in line:
                            if 0 <= step_index < len(steps):
                                steps[step_index]["status"] = "success"
                                yield send_event("step_update", {"step": steps[step_index]})

                        if "\u2717" in line:
                            if 0 <= step_index < len(steps):
                                steps[step_index]["status"] = "error"
                                yield send_event("step_update", {"step": steps[step_index]})

                if channel.exit_status_ready():
                    while channel.recv_ready():
                        chunk = channel.recv(4096).decode("utf-8", errors="replace")
                        buffer += chunk
                    for line in buffer.split("\n"):
                        line = line.strip()
                        if line:
                            yield send_event("log", {"message": line})
                    break

                await asyncio.sleep(0.1)

            exit_status = channel.recv_exit_status()

            if exit_status == 0:
                from app.db import GetDB
                with GetDB() as inner_db:
                    crud.set_adguard_installed(inner_db, node_id, True)
                yield send_event("complete", {
                    "success": True,
                    "message": "AdGuard Home installed successfully",
                })
            else:
                yield send_event("complete", {
                    "success": False,
                    "message": f"Installation failed with exit code {exit_status}",
                })

        except Exception as e:
            logger.error("AdGuard install error: %s", e, exc_info=True)
            yield send_event("error", {"message": f"Install error: {e}"})
            yield send_event("complete", {"success": False, "message": str(e)})
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
        },
    )
