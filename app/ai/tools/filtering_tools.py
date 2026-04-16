"""AI tools for per-node ad-blocking / DNS filtering.

The panel stores a `NodeFilteringConfig` row per node that controls:

    - `adblock_enabled`: whether the Xray config is patched with the
      `geosite:category-ads-all` routing rule and a `block` outbound.
    - `dns_provider`: which DNS servers Xray resolves through
      (AdGuard Home local, AdGuard DNS public, NextDNS, Cloudflare
      security, or custom).
    - `dns_address`: custom DNS endpoint (IP/URL) or NextDNS config id.
    - `adguard_home_port`: the UDP port AdGuard Home listens on locally.
    - `adguard_home_installed`: flipped to True after the AdGuard Home
      container is deployed via SSH.

Tools exposed here:

    get_node_filtering        — read current config (+ live adguard
                                container state, if SSH is unlocked).
    list_nodes_filtering      — read config across all nodes.
    set_node_filtering        — update config fields and reapply
                                the Xray patch, restart the backend.
    install_adguard_home      — deploy AdGuard Home on a node via SSH.

All writes are `requires_confirmation=True`. Installation additionally
requires the chat session to be SSH-unlocked (see `ssh_tools`).
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from sqlalchemy.orm import Session

from app.ai.session_context import get_current_session_id
from app.ai.ssh_runner import (
    DEFAULT_TIMEOUT_SEC,
    decrypt_node_credentials,
    upload_and_run_script,
)
from app.ai.ssh_session import get_unlocked_pin
from app.ai.tool_registry import register_tool
from app.models.node_filtering import DnsProvider, NodeFilteringConfigUpdate
from app.utils.xray_config_patcher import (
    patch_config_disable,
    patch_config_enable,
)

logger = logging.getLogger(__name__)

_VALID_DNS_PROVIDERS = sorted(p.value for p in DnsProvider)
_ADGUARD_INSTALL_TIMEOUT_SEC = 300
_ADGUARD_INSTALL_SCRIPT_NAME = "install_adguard.sh"
_ADGUARD_INSTALL_REMOTE_PATH = "/tmp/install_adguard.sh"


def _serialize_filtering(cfg) -> dict:
    if cfg is None:
        return {"configured": False}
    return {
        "configured": True,
        "adblock_enabled": bool(cfg.adblock_enabled),
        "dns_provider": cfg.dns_provider.value if cfg.dns_provider else None,
        "dns_address": cfg.dns_address,
        "adguard_home_port": cfg.adguard_home_port,
        "adguard_home_installed": bool(cfg.adguard_home_installed),
    }


def _read_install_script() -> str:
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    path = os.path.join(here, _ADGUARD_INSTALL_SCRIPT_NAME)
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


@register_tool(
    name="get_node_filtering",
    description=(
        "Get the current ad-blocking / DNS filtering configuration for a "
        "specific node. Returns: configured, adblock_enabled, dns_provider "
        f"(one of {', '.join(_VALID_DNS_PROVIDERS)}), dns_address, "
        "adguard_home_port, adguard_home_installed. Read-only."
    ),
    requires_confirmation=False,
)
async def get_node_filtering(db: Session, node_id: int) -> dict:
    from app.db import crud

    node = crud.get_node_by_id(db, node_id)
    if not node:
        return {"error": f"Node {node_id} not found"}

    cfg = crud.get_filtering_config(db, node_id)
    payload = _serialize_filtering(cfg)
    payload.update({"node_id": node_id, "node_name": node.name})
    return payload


@register_tool(
    name="list_nodes_filtering",
    description=(
        "List ad-blocking / DNS filtering configuration for all nodes at "
        "once. Useful to spot nodes with divergent adblock state or DNS "
        "provider before making a fleet-wide change. Read-only."
    ),
    requires_confirmation=False,
)
async def list_nodes_filtering(db: Session) -> dict:
    from app.db import crud
    from app.db.models import Node

    nodes = db.query(Node).all()
    result = []
    for n in nodes:
        cfg = crud.get_filtering_config(db, n.id)
        row = _serialize_filtering(cfg)
        row["node_id"] = n.id
        row["node_name"] = n.name
        row["node_address"] = n.address
        result.append(row)

    enabled = sum(1 for r in result if r.get("adblock_enabled"))
    installed = sum(1 for r in result if r.get("adguard_home_installed"))
    return {
        "nodes": result,
        "summary": {
            "total": len(result),
            "adblock_enabled": enabled,
            "adguard_installed": installed,
        },
    }


@register_tool(
    name="set_node_filtering",
    description=(
        "Update ad-blocking / DNS filtering for a node and re-apply the "
        "patch to the live Xray config (restarts xray backend). "
        "Any unspecified field is left unchanged. "
        f"dns_provider must be one of: {', '.join(_VALID_DNS_PROVIDERS)}. "
        "For `custom` use `dns_address` to pass an explicit DNS IP/URL; "
        "for `nextdns` `dns_address` is the NextDNS config id. "
        "`adguard_home_local` only makes sense after AdGuard Home has "
        "been installed (see install_adguard_home). "
        "Pass adblock_enabled=-1 to leave the toggle untouched; 0 or 1 "
        "to set it. Returns the stored config after the update."
    ),
    requires_confirmation=True,
)
async def set_node_filtering(
    db: Session,
    node_id: int,
    adblock_enabled: int = -1,
    dns_provider: str = "",
    dns_address: str = "",
    adguard_home_port: int = 0,
) -> dict:
    from app.db import crud
    from app.marznode import node_registry

    node = crud.get_node_by_id(db, node_id)
    if not node:
        return {"error": f"Node {node_id} not found"}

    update_kwargs: dict = {}
    if adblock_enabled in (0, 1):
        update_kwargs["adblock_enabled"] = bool(adblock_enabled)
    if dns_provider:
        try:
            update_kwargs["dns_provider"] = DnsProvider(dns_provider)
        except ValueError:
            return {
                "error": (
                    f"Invalid dns_provider '{dns_provider}'. "
                    f"Allowed: {', '.join(_VALID_DNS_PROVIDERS)}."
                )
            }
    # Treat empty string as "unchanged"; use the literal sentinel
    # "__clear__" to wipe a custom DNS address.
    if dns_address == "__clear__":
        update_kwargs["dns_address"] = None
    elif dns_address:
        update_kwargs["dns_address"] = dns_address
    if adguard_home_port and 1 <= adguard_home_port <= 65535:
        update_kwargs["adguard_home_port"] = adguard_home_port

    if not update_kwargs:
        return {"error": "No fields to update"}

    update = NodeFilteringConfigUpdate(**update_kwargs)
    cfg = crud.update_filtering_config(db, node_id, update)

    backend_names = [b.name for b in node.backends]
    db.close()

    marznode_ref = node_registry.get(node_id)
    patched_backends: list[str] = []
    skipped_backends: list[dict] = []

    if marznode_ref is None:
        return {
            "success": True,
            "warning": (
                f"Node {node_id} is not connected — config saved but xray "
                "backend was NOT restarted. Reconnect the node or wait for "
                "reconciliation."
            ),
            "config": _serialize_filtering(cfg),
        }

    for backend_name in backend_names:
        try:
            config_str, config_format = await marznode_ref.get_backend_config(
                name=backend_name
            )
        except Exception as exc:
            skipped_backends.append({"backend": backend_name, "reason": f"fetch failed: {exc}"})
            continue

        if int(config_format) != 1:
            skipped_backends.append(
                {"backend": backend_name, "reason": f"unsupported format {config_format}"}
            )
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
                    name=backend_name, config=patched, config_format=config_format
                ),
                timeout=60,
            )
            patched_backends.append(backend_name)
        except Exception as exc:
            skipped_backends.append({"backend": backend_name, "reason": str(exc)})

    return {
        "success": True,
        "node_id": node_id,
        "patched_backends": patched_backends,
        "skipped_backends": skipped_backends,
        "config": _serialize_filtering(cfg),
    }


@register_tool(
    name="install_adguard_home",
    description=(
        "Deploy AdGuard Home on a node via SSH (Docker container). Idempotent: "
        "running twice on the same node upgrades / refreshes the container. "
        "Requires the chat session to be SSH-unlocked (see ssh_check_access) "
        "and stored SSH credentials for the node. On success, marks the "
        "node's adguard_home_installed=True and returns the install log "
        "tail. After install, consider set_node_filtering with "
        "dns_provider=adguard_home_local to route Xray DNS through it."
    ),
    requires_confirmation=True,
)
async def install_adguard_home(db: Session, node_id: int) -> dict:
    from app.db import crud

    session_id = get_current_session_id()
    if not session_id:
        return {"error": "No active chat session", "code": "NO_SESSION"}

    pin = get_unlocked_pin(session_id)
    if not pin:
        return {
            "error": (
                "SSH is not unlocked for this session. The admin must enter "
                "the PIN in the SSH dialog first."
            ),
            "code": "SSH_LOCKED",
            "node_id": node_id,
        }

    node = crud.get_node_by_id(db, node_id)
    if not node:
        return {"error": f"Node {node_id} not found", "code": "NO_NODE"}

    creds_row = crud.get_ssh_credentials(db, node_id)
    if not creds_row:
        return {
            "error": (
                f"No stored SSH credentials for node {node_id}. The admin "
                "must save them via the SSH unlock dialog first."
            ),
            "code": "NO_CREDENTIALS",
        }

    try:
        creds = decrypt_node_credentials(creds_row, pin)
    except PermissionError as exc:
        return {"error": str(exc), "code": "AUTH_FAILED"}

    cfg = crud.get_or_create_filtering_config(db, node_id)
    adguard_port = cfg.adguard_home_port or 5353
    host = node.address
    db.close()

    try:
        script_text = _read_install_script()
    except OSError as exc:
        return {"error": f"Install script not found: {exc}", "code": "NO_SCRIPT"}

    try:
        result = await asyncio.to_thread(
            upload_and_run_script,
            host=host,
            creds=creds,
            script_text=script_text,
            remote_path=_ADGUARD_INSTALL_REMOTE_PATH,
            args=str(adguard_port),
            timeout=_ADGUARD_INSTALL_TIMEOUT_SEC,
        )
    except PermissionError as exc:
        return {"error": str(exc), "code": "AUTH_FAILED"}
    except TimeoutError as exc:
        return {"error": str(exc), "code": "TIMEOUT"}
    except Exception as exc:
        logger.exception("install_adguard_home failed")
        return {"error": f"AdGuard install failed: {exc}", "code": "EXEC_ERROR"}

    if result.success:
        from app.db import GetDB
        with GetDB() as inner_db:
            crud.set_adguard_installed(inner_db, node_id, True)

    tail_lines = result.stdout.splitlines()[-40:]
    return {
        "success": result.success,
        "exit_code": result.exit_code,
        "elapsed_ms": result.elapsed_ms,
        "host": host,
        "adguard_home_port": adguard_port,
        "stdout_tail": "\n".join(tail_lines),
        "stderr_tail": "\n".join(result.stderr.splitlines()[-20:]),
        "truncated": result.truncated,
        "message": (
            f"AdGuard Home deployed on {host}:{adguard_port}."
            if result.success
            else f"AdGuard install exited with code {result.exit_code}."
        ),
    }
