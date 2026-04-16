"""AI tools for SSH access to nodes.

Two tools are exposed:

- `ssh_check_access`: read-only. The agent calls this first to learn
  whether SSH is usable for a given node — i.e. whether the admin has
  configured the global PIN, stored credentials for the node, and
  unlocked the chat session.

- `ssh_run_command`: executes a shell command on a node. It is gated
  by the standard confirmation flow (`requires_confirmation=True`) and
  also requires that the chat session be SSH-unlocked. Output is
  capped at 64 KiB per stream and 60 s timeout by default.
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy.orm import Session

from app.ai.session_context import get_current_session_id
from app.ai.ssh_runner import (
    DEFAULT_TIMEOUT_SEC,
    MAX_TIMEOUT_SEC,
    decrypt_node_credentials,
    run_command_with_creds,
    validate_command,
)
from app.ai.ssh_session import (
    SSH_UNLOCK_TTL_SEC,
    get_ttl_seconds,
    get_unlocked_pin,
    is_session_unlocked,
)
from app.ai.tool_registry import register_tool
from app.db import crud

logger = logging.getLogger(__name__)


@register_tool(
    name="ssh_check_access",
    description=(
        "Check whether SSH access is usable for a given node in the current "
        "chat session. Returns: pin_configured (global SSH PIN set by admin), "
        "session_unlocked (admin entered the PIN in this chat), "
        "credentials_saved (per-node SSH user/password/key stored), "
        "ssh_ready (all three prerequisites met). "
        "Always call this BEFORE ssh_run_command to decide whether you can "
        "run a remote command or must first ask the admin to unlock SSH. "
        "If ssh_ready is false, explain to the admin what's missing and "
        "stop — the UI will pop up the SSH unlock dialog on the next "
        "ssh_run_command attempt."
    ),
    requires_confirmation=False,
)
async def ssh_check_access(db: Session, node_id: int) -> dict:
    node = crud.get_node_by_id(db, node_id)
    if not node:
        return {"error": f"Node {node_id} not found"}

    pin_hash = crud.get_ssh_pin_hash(db)
    creds_row = crud.get_ssh_credentials(db, node_id)
    session_id = get_current_session_id()

    pin_configured = pin_hash is not None
    credentials_saved = creds_row is not None
    session_unlocked = bool(session_id) and is_session_unlocked(session_id)
    ttl = get_ttl_seconds(session_id) if session_id else 0

    return {
        "node_id": node_id,
        "node_address": node.address,
        "pin_configured": pin_configured,
        "credentials_saved": credentials_saved,
        "session_unlocked": session_unlocked,
        "unlock_ttl_seconds": ttl,
        "ssh_ready": pin_configured and credentials_saved and session_unlocked,
        "missing": [
            item for item, ok in [
                ("pin_configured", pin_configured),
                ("credentials_saved", credentials_saved),
                ("session_unlocked", session_unlocked),
            ] if not ok
        ],
    }


@register_tool(
    name="ssh_run_command",
    description=(
        "Execute a shell command on a node via SSH and return stdout, stderr "
        "and exit code. Use this for diagnostics the panel API cannot cover "
        "(e.g. checking /usr/local/bin/xray, inspecting systemd, looking at "
        "docker containers, fixing failed installs). "
        f"Output is capped at 64KiB per stream and timeout defaults to "
        f"{DEFAULT_TIMEOUT_SEC}s (max {MAX_TIMEOUT_SEC}s). "
        "The chat session MUST be SSH-unlocked first (see ssh_check_access); "
        "if it isn't, this tool will return an error with code SSH_LOCKED "
        "and the UI will prompt the admin for PIN/credentials. "
        "Never pass interactive commands — pipe inputs explicitly. "
        "Prefer the narrowest command possible; do not run destructive "
        "operations unless the admin explicitly asked for them."
    ),
    requires_confirmation=True,
)
async def ssh_run_command(
    db: Session,
    node_id: int,
    command: str,
    timeout: int = DEFAULT_TIMEOUT_SEC,
) -> dict:
    err = validate_command(command)
    if err:
        return {"error": err, "code": "FORBIDDEN_COMMAND"}

    session_id = get_current_session_id()
    if not session_id:
        return {
            "error": "No active chat session — cannot resolve SSH PIN",
            "code": "NO_SESSION",
        }

    pin = get_unlocked_pin(session_id)
    if not pin:
        return {
            "error": (
                "SSH is not unlocked for this chat session. Ask the admin "
                "to enter the SSH PIN in the dialog. After unlock, call "
                "this tool again."
            ),
            "code": "SSH_LOCKED",
            "node_id": node_id,
            "unlock_ttl_seconds": SSH_UNLOCK_TTL_SEC,
        }

    node = crud.get_node_by_id(db, node_id)
    if not node:
        return {"error": f"Node {node_id} not found", "code": "NO_NODE"}

    creds_row = crud.get_ssh_credentials(db, node_id)
    if not creds_row:
        return {
            "error": (
                f"No stored SSH credentials for node {node_id}. The admin "
                "must save them first via the SSH unlock dialog."
            ),
            "code": "NO_CREDENTIALS",
            "node_id": node_id,
        }

    host = node.address
    try:
        creds = decrypt_node_credentials(creds_row, pin)
    except PermissionError as exc:
        return {"error": str(exc), "code": "AUTH_FAILED"}

    db.close()

    try:
        result = await asyncio.to_thread(
            run_command_with_creds,
            host=host,
            creds=creds,
            command=command,
            timeout=timeout,
        )
    except PermissionError as exc:
        return {"error": str(exc), "code": "AUTH_FAILED"}
    except TimeoutError as exc:
        return {"error": str(exc), "code": "TIMEOUT"}
    except Exception as exc:
        logger.exception("ssh_run_command failed")
        return {"error": f"SSH execution failed: {exc}", "code": "EXEC_ERROR"}

    logger.info(
        "ssh_run_command session=%s node=%s cmd='%s' exit=%d truncated=%s",
        session_id,
        node_id,
        command[:80],
        result.exit_code,
        result.truncated,
    )
    return result.to_dict()
