"""Run a shell command on a node via SSH, using stored credentials.

The function resolves per-node `NodeSSHCredentials`, decrypts them with
the raw PIN cached for the current chat session
(`app.ai.ssh_session`), connects via paramiko, executes the requested
command with hard caps on both duration and output size, and returns a
structured result.

This module intentionally stays small and synchronous: the AI tool
wrapper will hand the call off to a worker thread via
`asyncio.to_thread` to avoid blocking the event loop.
"""
from __future__ import annotations

import io
import logging
import os
import time
from dataclasses import dataclass
from typing import Optional

import paramiko
from sqlalchemy.orm import Session

from app.config.db import get_secret_key
from app.db import crud
from app.utils.crypto import decrypt_credentials

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SEC = 60
MAX_TIMEOUT_SEC = 300
MAX_OUTPUT_BYTES = 64 * 1024  # 64 KiB cap per stream

# Minimum set of destructive command fragments the agent must never
# invoke without the admin seeing them spelled out first. The tool
# layer already runs behind `requires_confirmation=True`, so this is
# defence in depth against a compromised or confused model.
_FORBIDDEN_FRAGMENTS = (
    "rm -rf /",
    "mkfs",
    ":(){:|:&};:",  # fork bomb
    "> /dev/sda",
    "dd if=/dev/zero of=/dev/sd",
)


@dataclass
class SSHCommandResult:
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    truncated: bool
    elapsed_ms: int
    host: str
    user: str

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "truncated": self.truncated,
            "elapsed_ms": self.elapsed_ms,
            "host": self.host,
            "user": self.user,
        }


def _load_pkey(key_str: str):
    """Try parsing a private key string as RSA / Ed25519 / ECDSA in turn."""
    key_file = io.StringIO(key_str)
    for key_cls in (paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey):
        try:
            key_file.seek(0)
            return key_cls.from_private_key(key_file)
        except (paramiko.SSHException, ValueError):
            continue
    raise ValueError("Unsupported SSH key format")


def _open_ssh(
    host: str,
    creds: dict,
    timeout: int,
) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    connect_kwargs = {
        "hostname": host,
        "port": creds.get("ssh_port") or 22,
        "username": creds.get("ssh_user") or "root",
        "timeout": timeout,
        "banner_timeout": timeout,
        "auth_timeout": timeout,
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
            connect_kwargs["pkey"] = _load_pkey(key_str)
    else:
        raise ValueError("Stored SSH credentials lack both password and key")

    client.connect(**connect_kwargs)
    return client


def _exec_with_caps(
    client: paramiko.SSHClient,
    command: str,
    timeout: int,
) -> tuple[int, str, str, bool]:
    """Run `command`, enforcing overall timeout and per-stream size cap."""
    transport = client.get_transport()
    if transport is None:
        raise RuntimeError("SSH transport is not available")
    channel = transport.open_session()
    channel.settimeout(timeout)
    channel.exec_command(command)

    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []
    stdout_total = 0
    stderr_total = 0
    truncated = False

    deadline = time.monotonic() + timeout
    while True:
        did_read = False

        if channel.recv_ready():
            chunk = channel.recv(4096)
            did_read = True
            if stdout_total < MAX_OUTPUT_BYTES:
                remaining = MAX_OUTPUT_BYTES - stdout_total
                if len(chunk) > remaining:
                    stdout_chunks.append(chunk[:remaining])
                    stdout_total += remaining
                    truncated = True
                else:
                    stdout_chunks.append(chunk)
                    stdout_total += len(chunk)
            else:
                truncated = True

        if channel.recv_stderr_ready():
            chunk = channel.recv_stderr(4096)
            did_read = True
            if stderr_total < MAX_OUTPUT_BYTES:
                remaining = MAX_OUTPUT_BYTES - stderr_total
                if len(chunk) > remaining:
                    stderr_chunks.append(chunk[:remaining])
                    stderr_total += remaining
                    truncated = True
                else:
                    stderr_chunks.append(chunk)
                    stderr_total += len(chunk)
            else:
                truncated = True

        if channel.exit_status_ready():
            # Drain any remaining buffered output before breaking out.
            while channel.recv_ready() or channel.recv_stderr_ready():
                if channel.recv_ready():
                    chunk = channel.recv(4096)
                    if stdout_total < MAX_OUTPUT_BYTES:
                        remaining = MAX_OUTPUT_BYTES - stdout_total
                        stdout_chunks.append(chunk[:remaining])
                        stdout_total += min(len(chunk), remaining)
                        if len(chunk) > remaining:
                            truncated = True
                if channel.recv_stderr_ready():
                    chunk = channel.recv_stderr(4096)
                    if stderr_total < MAX_OUTPUT_BYTES:
                        remaining = MAX_OUTPUT_BYTES - stderr_total
                        stderr_chunks.append(chunk[:remaining])
                        stderr_total += min(len(chunk), remaining)
                        if len(chunk) > remaining:
                            truncated = True
            break

        if time.monotonic() > deadline:
            try:
                channel.close()
            except Exception:
                pass
            raise TimeoutError(f"Command exceeded {timeout}s timeout")

        if not did_read:
            time.sleep(0.05)

    exit_code = channel.recv_exit_status()
    stdout = b"".join(stdout_chunks).decode("utf-8", errors="replace")
    stderr = b"".join(stderr_chunks).decode("utf-8", errors="replace")
    return exit_code, stdout, stderr, truncated


def validate_command(command: str) -> Optional[str]:
    """Return an error string if the command is obviously dangerous."""
    if not command or not command.strip():
        return "Command must not be empty"
    lowered = command.lower()
    for frag in _FORBIDDEN_FRAGMENTS:
        if frag in lowered:
            return (
                f"Refusing to run command containing forbidden fragment "
                f"'{frag}'. Ask the admin to run it manually if truly needed."
            )
    return None


def decrypt_node_credentials(creds_row, pin: str) -> dict:
    """Decrypt the stored credentials row; raises PermissionError on bad PIN."""
    secret = get_secret_key()
    try:
        return decrypt_credentials(
            creds_row.encrypted_data, creds_row.encryption_salt, pin, secret
        )
    except ValueError:
        raise PermissionError("Invalid PIN — credential decryption failed")


def run_command_with_creds(
    host: str,
    creds: dict,
    command: str,
    timeout: int = DEFAULT_TIMEOUT_SEC,
) -> SSHCommandResult:
    """Connect via SSH using already-decrypted creds and run `command`.

    This is the low-level entry point used by the AI `ssh_run_command`
    tool. It is safe to hand off to a worker thread via
    `asyncio.to_thread` — no SQLAlchemy session is touched here.
    """
    timeout = max(1, min(int(timeout or DEFAULT_TIMEOUT_SEC), MAX_TIMEOUT_SEC))
    user = creds.get("ssh_user") or "root"

    started = time.monotonic()
    client: Optional[paramiko.SSHClient] = None
    try:
        client = _open_ssh(host, creds, timeout)
        exit_code, stdout, stderr, truncated = _exec_with_caps(
            client, command, timeout
        )
    except paramiko.AuthenticationException as exc:
        raise PermissionError(f"SSH authentication failed: {exc}")
    except (paramiko.SSHException, OSError) as exc:
        raise RuntimeError(f"SSH connection error: {exc}")
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass

    elapsed_ms = int((time.monotonic() - started) * 1000)
    return SSHCommandResult(
        success=(exit_code == 0),
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        truncated=truncated,
        elapsed_ms=elapsed_ms,
        host=host,
        user=user,
    )


def resolve_and_run(
    db: Session,
    node_id: int,
    command: str,
    pin: str,
    timeout: int = DEFAULT_TIMEOUT_SEC,
) -> SSHCommandResult:
    """Convenience wrapper: DB lookup + decrypt + run. DB is needed."""
    node = crud.get_node_by_id(db, node_id)
    if not node:
        raise LookupError(f"Node {node_id} not found")

    creds_row = crud.get_ssh_credentials(db, node_id)
    if not creds_row:
        raise LookupError(
            f"No stored SSH credentials for node {node_id}. "
            "The admin must save credentials via the SSH unlock dialog first."
        )

    creds = decrypt_node_credentials(creds_row, pin)
    return run_command_with_creds(node.address, creds, command, timeout)
