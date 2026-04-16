"""AI tools for SSH access to nodes.

Three tools are exposed:

- `ssh_check_access`: read-only. The agent calls this first to learn
  whether SSH is usable for a given node — i.e. whether the admin has
  configured the global PIN, stored credentials for the node, and
  unlocked the chat session.

- `ssh_run_command`: executes a single shell command on a node. Gated
  by the standard confirmation flow (`requires_confirmation=True`) and
  requires the chat session to be SSH-unlocked. Output is capped at
  64 KiB per stream and 60 s timeout by default.

- `ssh_run_batch`: executes MULTIPLE shell commands over a single SSH
  connection and returns one structured result per command. Same
  confirmation / unlock requirements as `ssh_run_command`. Strongly
  preferred over calling `ssh_run_command` N times back-to-back because
  it amortises the SSH handshake and cuts the confirmation dialog
  noise down to one approval for the whole batch.
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
    run_commands_with_creds,
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

MAX_BATCH_COMMANDS = 20


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


def _normalise_batch(commands: list) -> tuple[list[str], list[str], str | None]:
    """Accept [str, ...] or [{"name": ..., "command": ...}, ...]."""
    raw_cmds: list[str] = []
    labels: list[str] = []
    for idx, item in enumerate(commands):
        if isinstance(item, str):
            cmd = item
            label = f"cmd{idx + 1}"
        elif isinstance(item, dict):
            cmd = item.get("command") or item.get("cmd") or ""
            label = str(item.get("name") or item.get("label") or f"cmd{idx + 1}")
        else:
            return [], [], (
                f"commands[{idx}] must be a string or object with 'command' "
                f"field, got {type(item).__name__}"
            )
        if not cmd or not str(cmd).strip():
            return [], [], f"commands[{idx}] ('{label}') is empty"
        err = validate_command(str(cmd))
        if err:
            return [], [], f"commands[{idx}] ('{label}'): {err}"
        raw_cmds.append(str(cmd))
        labels.append(label)
    return raw_cmds, labels, None


@register_tool(
    name="ssh_run_batch",
    description=(
        "Run MULTIPLE shell commands on a single node in one SSH connection "
        "and return structured per-command results. Prefer this over "
        "calling ssh_run_command several times in a row — one TCP+auth "
        "handshake, one confirmation dialog, much lower latency. "
        "`commands` is a list of either plain strings OR objects "
        "{name: string, command: string} (the name is echoed back in "
        "results for easier correlation; defaults to 'cmd1', 'cmd2'...). "
        f"Up to {MAX_BATCH_COMMANDS} commands per call. Per-command timeout "
        f"defaults to {DEFAULT_TIMEOUT_SEC}s (max {MAX_TIMEOUT_SEC}s); "
        "output capped at 64KiB per stream per command. "
        "Set stop_on_error=true when later commands only make sense if "
        "earlier ones succeeded (e.g. 'cd X && do Y'); otherwise all "
        "commands are attempted and their individual exit codes reported. "
        "Requires the chat session to be SSH-unlocked (see ssh_check_access) "
        "and per-node credentials saved; returns SSH_LOCKED or "
        "NO_CREDENTIALS otherwise. Same destructive-command guardrails as "
        "ssh_run_command apply to EACH command in the batch."
    ),
    requires_confirmation=True,
)
async def ssh_run_batch(
    db: Session,
    node_id: int,
    commands: list,
    timeout: int = DEFAULT_TIMEOUT_SEC,
    stop_on_error: bool = False,
) -> dict:
    if not isinstance(commands, list) or not commands:
        return {
            "error": "commands must be a non-empty list",
            "code": "BAD_ARGS",
        }
    if len(commands) > MAX_BATCH_COMMANDS:
        return {
            "error": (
                f"commands has {len(commands)} entries; max {MAX_BATCH_COMMANDS} "
                "per batch. Split the work across multiple ssh_run_batch calls."
            ),
            "code": "BAD_ARGS",
        }

    raw_cmds, labels, err = _normalise_batch(commands)
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
        raw_results = await asyncio.to_thread(
            run_commands_with_creds,
            host=host,
            creds=creds,
            commands=raw_cmds,
            timeout=timeout,
            stop_on_error=bool(stop_on_error),
        )
    except PermissionError as exc:
        return {"error": str(exc), "code": "AUTH_FAILED"}
    except Exception as exc:
        logger.exception("ssh_run_batch failed")
        return {"error": f"SSH batch execution failed: {exc}", "code": "EXEC_ERROR"}

    per_command: list[dict] = []
    total_elapsed_ms = 0
    any_truncated = False
    all_ok = True
    for label, cmd, res in zip(labels, raw_cmds, raw_results):
        entry = res.to_dict()
        entry["name"] = label
        entry["command"] = cmd
        per_command.append(entry)
        total_elapsed_ms += res.elapsed_ms
        any_truncated = any_truncated or res.truncated
        all_ok = all_ok and res.success

    skipped = len(raw_cmds) - len(raw_results)
    stopped_early = stop_on_error and skipped > 0

    logger.info(
        "ssh_run_batch session=%s node=%s count=%d stopped_early=%s all_ok=%s",
        session_id,
        node_id,
        len(per_command),
        stopped_early,
        all_ok,
    )
    return {
        "success": all_ok and not stopped_early,
        "node_id": node_id,
        "host": host,
        "commands_total": len(raw_cmds),
        "commands_executed": len(per_command),
        "stopped_early": stopped_early,
        "any_truncated": any_truncated,
        "total_elapsed_ms": total_elapsed_ms,
        "results": per_command,
    }
