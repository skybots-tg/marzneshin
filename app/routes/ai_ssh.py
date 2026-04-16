"""SSH unlock endpoints for the AI chat.

The flow:

1. UI detects `pending_confirmation` for `ssh_run_command` (or for any
   other future SSH tool). It calls `GET /ai/ssh/status` with the
   session id and the tool's `node_id` to learn what the user needs to
   provide (PIN only vs. PIN + credentials).

2. UI shows a dialog. On submit:
   - If credentials already exist → `POST /ai/ssh/unlock` with PIN.
   - Else → `POST /ai/ssh/credentials` with PIN + user/port + password
     or key. This endpoint both saves the credentials (reusing the
     existing per-node storage) and unlocks the session.

3. After a successful unlock, the UI proceeds with the normal
   confirmation (`POST /ai/chat/confirm` with action=approve), and
   the tool handler picks up the session-scoped PIN to run the
   command.

4. When the chat is cleared, the UI can call `POST /ai/ssh/lock`
   to forget the PIN immediately; otherwise it expires after
   `SSH_UNLOCK_TTL_SEC`.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.ai.ssh_session import (
    SSH_UNLOCK_TTL_SEC,
    get_ttl_seconds,
    is_session_unlocked,
    lock_session,
    unlock_session,
)
from app.config.db import get_secret_key
from app.db import crud
from app.dependencies import DBDep, SudoAdminDep
from app.utils.crypto import encrypt_credentials, verify_pin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ai/ssh", tags=["AI Assistant"])


class SSHStatusResponse(BaseModel):
    pin_configured: bool
    credentials_saved: bool
    session_unlocked: bool
    unlock_ttl_seconds: int
    node_id: int | None = None
    node_address: str | None = None
    ssh_user: str | None = None
    ssh_port: int | None = None


class SSHUnlockBody(BaseModel):
    session_id: str = Field(min_length=1)
    pin: str = Field(min_length=4, max_length=4, pattern=r"^\d{4}$")


class SSHCredentialsBody(BaseModel):
    session_id: str = Field(min_length=1)
    node_id: int
    pin: str = Field(min_length=4, max_length=4, pattern=r"^\d{4}$")
    ssh_user: str = "root"
    ssh_port: int = Field(default=22, ge=1, le=65535)
    ssh_password: str | None = None
    ssh_key: str | None = None


class SSHLockBody(BaseModel):
    session_id: str = Field(min_length=1)


@router.get("/status", response_model=SSHStatusResponse)
def ssh_status(
    session_id: str,
    db: DBDep,
    admin: SudoAdminDep,
    node_id: int | None = None,
):
    pin_hash = crud.get_ssh_pin_hash(db)
    pin_configured = pin_hash is not None

    creds_row = None
    node_address = None
    if node_id is not None:
        node = crud.get_node_by_id(db, node_id)
        if node:
            node_address = node.address
            creds_row = crud.get_ssh_credentials(db, node_id)

    # NodeSSHCredentials stores only encrypted blob — we never expose
    # ssh_user / ssh_port until unlocked. For the dialog, the admin
    # will re-enter them only when saving new credentials anyway.
    return SSHStatusResponse(
        pin_configured=pin_configured,
        credentials_saved=creds_row is not None,
        session_unlocked=is_session_unlocked(session_id),
        unlock_ttl_seconds=get_ttl_seconds(session_id),
        node_id=node_id,
        node_address=node_address,
    )


@router.post("/unlock", response_model=SSHStatusResponse)
def ssh_unlock(body: SSHUnlockBody, db: DBDep, admin: SudoAdminDep):
    pin_hash = crud.get_ssh_pin_hash(db)
    if not pin_hash:
        raise HTTPException(
            status_code=400,
            detail="Global SSH PIN is not configured. Set it in system settings first.",
        )
    if not verify_pin(body.pin, pin_hash):
        raise HTTPException(status_code=403, detail="Invalid PIN")

    unlock_session(body.session_id, body.pin)
    return SSHStatusResponse(
        pin_configured=True,
        credentials_saved=False,
        session_unlocked=True,
        unlock_ttl_seconds=SSH_UNLOCK_TTL_SEC,
    )


@router.post("/credentials", response_model=SSHStatusResponse)
def ssh_save_credentials(
    body: SSHCredentialsBody, db: DBDep, admin: SudoAdminDep
):
    if not body.ssh_password and not body.ssh_key:
        raise HTTPException(
            status_code=400,
            detail="Either ssh_password or ssh_key is required",
        )

    node = crud.get_node_by_id(db, body.node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    pin_hash = crud.get_ssh_pin_hash(db)
    if not pin_hash:
        raise HTTPException(
            status_code=400,
            detail="Global SSH PIN is not configured. Set it in system settings first.",
        )
    if not verify_pin(body.pin, pin_hash):
        raise HTTPException(status_code=403, detail="Invalid PIN")

    secret = get_secret_key()
    payload = {
        "ssh_user": body.ssh_user,
        "ssh_port": body.ssh_port,
        "ssh_password": body.ssh_password,
        "ssh_key": body.ssh_key,
    }
    encrypted_data, salt = encrypt_credentials(payload, body.pin, secret)
    crud.save_ssh_credentials(db, body.node_id, encrypted_data, salt)

    unlock_session(body.session_id, body.pin)
    return SSHStatusResponse(
        pin_configured=True,
        credentials_saved=True,
        session_unlocked=True,
        unlock_ttl_seconds=SSH_UNLOCK_TTL_SEC,
        node_id=body.node_id,
        node_address=node.address,
        ssh_user=body.ssh_user,
        ssh_port=body.ssh_port,
    )


@router.post("/lock")
def ssh_lock(body: SSHLockBody, admin: SudoAdminDep):
    removed = lock_session(body.session_id)
    return {"locked": True, "removed": removed}
