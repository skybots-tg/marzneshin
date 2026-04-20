"""AI tools for node provisioning / mass-fix operations.

Two tools live here:

- `install_panel_certificate_on_node` — write the panel's current TLS
  client certificate into ``/var/lib/marznode/client.pem`` on the
  target node and bounce the marznode service. This collapses what
  used to be 4-5 manual SSH steps into a single, idempotent fix for
  the textbook mTLS-mismatch failure mode (the one that pretended to
  be ``AttributeError: '_write_appdata'`` for hours).

- `onboard_node_from_donor` — the "make this new node look exactly
  like that one" macro. Mirrors the manual procedure the admin used
  to do by hand and collapses it into one confirmation:
    1. preflight (both nodes connected),
    2. `clone_node_config` (donor's xray JSON wholesale onto target,
       restart xray; panel auto-syncs target's inbound rows),
    3. `regenerate_reality_keys_on_node` on target (rotate per-node
       reality private_key + short_ids; optional, default ON),
    4. `propagate_node_to_services` (every service the donor was in
       gets the target's matching inbounds attached by tag),
    5. `clone_donor_hosts_to_target` (replicate every donor host
       onto the target's matching inbound, override address +
       remark + reality_public_key/short_ids from step 3),
    6. `resync_node_users` (push the user set to target xray),
    7. optional subscription verification on `sample_username`.
  Stops at the first hard failure and reports it in `failed_step`
  so the agent knows exactly where the chain broke without
  guessing.

Both tools require_confirmation=True — they actually mutate node
state.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.ai.session_context import get_current_session_id
from app.ai.ssh_runner import (
    decrypt_node_credentials,
    run_commands_with_creds,
    upload_and_run_script,
)
from app.ai.ssh_session import get_unlocked_pin, is_session_unlocked
from app.ai.tool_registry import register_tool
from app.ai.tools._common import canonical_panel_cert_bytes

logger = logging.getLogger(__name__)


# =============================================================================
# Helpers
# =============================================================================


def _load_creds(node_id: int) -> Optional[dict]:
    """Mirror of `_maybe_load_creds_for_node` in node_health_tools so
    we don't import across tool modules."""
    from app.db import GetDB, crud

    session_id = get_current_session_id()
    if not session_id or not is_session_unlocked(session_id):
        return None
    pin = get_unlocked_pin(session_id)
    if not pin:
        return None
    with GetDB() as db:
        creds_row = crud.get_ssh_credentials(db, node_id)
        if not creds_row:
            return None
        try:
            return decrypt_node_credentials(creds_row, pin)
        except PermissionError:
            return None


# =============================================================================
# 1. Install panel certificate on node — fixes mTLS mismatch
# =============================================================================


# Bash that overwrites client.pem and (best-effort) restarts marznode.
# We deliberately do NOT use `tee` for the cert content — we ship the
# cert as a pre-uploaded file via SFTP to avoid any shell-quoting hell
# with PEM newlines. The script just moves it into place.
_CERT_INSTALL_SCRIPT = r"""set +e
SRC="${1:-/tmp/marznode_client_panel.pem}"
DEST=/var/lib/marznode/client.pem

echo '### marker'
echo 'OK'
echo '### src_present'
if [ -r "$SRC" ]; then echo 'YES'; else echo 'NO'; fi
echo '### dest_dir_present'
if [ -d /var/lib/marznode ]; then echo 'YES'; else echo 'NO'; fi
echo '### prev_sha256'
sha256sum "$DEST" 2>/dev/null | awk '{print $1}'

if [ ! -r "$SRC" ] || [ ! -d /var/lib/marznode ]; then
  echo '### end'
  exit 2
fi

# Backup once per day so the admin can roll back if we clobbered the
# wrong cert. Using --preserve to keep mtime so we know when it was
# replaced.
TS=$(date -u +%Y%m%d-%H%M%S)
cp -p "$DEST" "${DEST}.bak-${TS}" 2>/dev/null

cp -p "$SRC" "$DEST"
chmod 600 "$DEST"

echo '### new_sha256'
sha256sum "$DEST" 2>/dev/null | awk '{print $1}'

echo '### restart'
RESTARTED='no'
# Prefer docker compose restart in /opt/marznode (typical install
# layout). Fall back to systemctl. Stay best-effort — even if restart
# fails, the new client.pem is in place and the panel will pick it up
# on the next reconnect cycle.
if [ -f /opt/marznode/compose.yml ] || [ -f /opt/marznode/docker-compose.yml ]; then
  if (cd /opt/marznode && docker compose restart marznode 2>&1) >/tmp/cert_restart.log; then
    RESTARTED='docker-compose'
  elif (cd /opt/marznode && docker-compose restart marznode 2>&1) >/tmp/cert_restart.log; then
    RESTARTED='docker-compose-legacy'
  fi
fi
if [ "$RESTARTED" = 'no' ] && command -v docker >/dev/null 2>&1; then
  CID=$(docker ps --filter name=marznode --format '{{.Names}}' | head -n1)
  if [ -n "$CID" ]; then
    if docker restart "$CID" 2>&1 >/tmp/cert_restart.log; then
      RESTARTED="docker-${CID}"
    fi
  fi
fi
if [ "$RESTARTED" = 'no' ] && command -v systemctl >/dev/null 2>&1; then
  if systemctl restart marznode 2>/tmp/cert_restart.log; then
    RESTARTED='systemd'
  fi
fi
echo "$RESTARTED"
echo '### restart_log'
tail -n 20 /tmp/cert_restart.log 2>/dev/null
echo '### end'
"""


def _split_marker_sections(stdout: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current = None
    buf: list[str] = []
    for line in stdout.splitlines():
        if line.startswith("### "):
            if current is not None:
                sections[current] = "\n".join(buf).strip()
            current = line[4:].strip()
            buf = []
        else:
            buf.append(line)
    if current is not None:
        sections[current] = "\n".join(buf).strip()
    return sections


@register_tool(
    name="install_panel_certificate_on_node",
    description=(
        "DESTRUCTIVE: ship the panel's current TLS client certificate "
        "(from the `tls` table) into `/var/lib/marznode/client.pem` "
        "on the target node and restart the marznode service so it "
        "picks up the new trust file. "
        "STRICT preconditions — call this ONLY if BOTH hold: "
        "(a) `verify_panel_certificate(node_id)` just returned "
        "`match=false` (or `node_client_pem_present=false`), AND "
        "(b) the same call's `marznode_ssl_envs.SSL_CLIENT_CERT_FILE` "
        "is the default `/var/lib/marznode/client.pem` (or unset). "
        "Do NOT call this preemptively during onboarding of a fresh "
        "marznode install — the marznode installer already places "
        "the right client.pem, so the node usually goes `healthy` on "
        "its own within 10-30s of `create_node`. Running this "
        "preemptively wastes a confirmation prompt and a service "
        "restart. "
        "Do NOT call this when `verify_panel_certificate` returned "
        "`match=true` — there is nothing to fix; running it just "
        "rewrites the same bytes and restarts marznode for no reason. "
        "Do NOT use this as a workaround for `node_not_loaded` — "
        "that's a panel-side registry state, fix it with "
        "`enable_node`. "
        "What the tool does, in order: "
        "(1) backs up the existing client.pem to "
        "client.pem.bak-<timestamp>, "
        "(2) overwrites client.pem with the panel cert (chmod 600), "
        "(3) tries `docker compose restart marznode` in /opt/marznode, "
        "falls back to `docker restart <container>` and finally "
        "`systemctl restart marznode`. "
        "The panel will reconnect to the node within ~10s of the "
        "restart (the monitor loop). After a successful run, follow "
        "up with `verify_panel_certificate` to confirm "
        "`match=true`, then `get_node_info` to confirm "
        "`status=healthy`. "
        "Requires SSH unlocked. Requires confirmation."
    ),
    requires_confirmation=True,
)
async def install_panel_certificate_on_node(
    db: Session, node_id: int, restart: bool = True
) -> dict:
    from app.db import crud, get_tls_certificate

    node = crud.get_node_by_id(db, node_id)
    if not node:
        return {"error": f"Node {node_id} not found"}
    node_address = node.address
    node_name = node.name

    tls = get_tls_certificate(db)
    if not tls or not tls.certificate:
        return {
            "error": (
                "Panel has no TLS certificate row to ship — run "
                "alembic migrations / regenerate via the admin tool."
            )
        }
    cert_bytes = canonical_panel_cert_bytes(tls)

    creds = _load_creds(node_id)
    if creds is None:
        return {
            "node_id": node_id,
            "ssh_available": False,
            "reason": (
                "SSH is not unlocked or credentials are missing for "
                "this node. Call ssh_check_access first."
            ),
        }

    db.close()

    # Step 1: SFTP the cert to a tmp path; Step 2: run the install
    # script that moves it into place + restarts. We do both in a
    # single SSH connection by using `upload_and_run_script` — the
    # script reads the cert from /tmp and copies it.
    # Two-stage upload: cert.pem -> /tmp, then script -> /tmp + run.
    import io
    import paramiko
    import time

    user = creds.get("ssh_user") or "root"
    started = time.monotonic()
    client: Optional[paramiko.SSHClient] = None
    try:
        from app.ai.ssh_runner import _open_ssh, _exec_with_caps  # type: ignore

        client = await asyncio.to_thread(_open_ssh, node_address, creds, 30)
        sftp = await asyncio.to_thread(client.open_sftp)
        try:
            payload = io.BytesIO(cert_bytes)
            await asyncio.to_thread(sftp.putfo, payload, "/tmp/marznode_client_panel.pem")
            await asyncio.to_thread(sftp.chmod, "/tmp/marznode_client_panel.pem", 0o600)

            script_payload = io.BytesIO(_CERT_INSTALL_SCRIPT.encode("utf-8"))
            await asyncio.to_thread(
                sftp.putfo, script_payload, "/tmp/marznode_install_cert.sh"
            )
            await asyncio.to_thread(
                sftp.chmod, "/tmp/marznode_install_cert.sh", 0o755
            )
        finally:
            await asyncio.to_thread(sftp.close)

        cmd = "bash /tmp/marznode_install_cert.sh /tmp/marznode_client_panel.pem"
        if not restart:
            cmd = "RESTART_SKIP=1 " + cmd
        exit_code, stdout, stderr, truncated = await asyncio.to_thread(
            _exec_with_caps, client, cmd, 90
        )
    except PermissionError as exc:
        return {
            "node_id": node_id,
            "ssh_available": False,
            "reason": f"SSH auth failed: {exc}",
        }
    except Exception as exc:
        logger.exception("install_panel_certificate_on_node failed")
        return {
            "node_id": node_id,
            "ssh_available": True,
            "reason": f"SSH execution failed: {exc}",
        }
    finally:
        if client is not None:
            try:
                await asyncio.to_thread(client.close)
            except Exception:
                pass

    sections = _split_marker_sections(stdout)
    src_present = (sections.get("src_present") or "").strip() == "YES"
    dest_dir_present = (sections.get("dest_dir_present") or "").strip() == "YES"
    prev_sha = (sections.get("prev_sha256") or "").strip().lower() or None
    new_sha = (sections.get("new_sha256") or "").strip().lower() or None
    restarted = (sections.get("restart") or "").strip() or "no"
    restart_log = sections.get("restart_log") or ""

    elapsed_ms = int((time.monotonic() - started) * 1000)

    if exit_code != 0 and not new_sha:
        return {
            "node_id": node_id,
            "node_name": node_name,
            "ssh_available": True,
            "success": False,
            "exit_code": exit_code,
            "src_present": src_present,
            "dest_dir_present": dest_dir_present,
            "prev_client_pem_sha256": prev_sha,
            "stderr": stderr,
            "elapsed_ms": elapsed_ms,
            "user": user,
        }

    return {
        "node_id": node_id,
        "node_name": node_name,
        "ssh_available": True,
        "success": True,
        "exit_code": exit_code,
        "host": node_address,
        "user": user,
        "prev_client_pem_sha256": prev_sha,
        "new_client_pem_sha256": new_sha,
        "cert_changed": prev_sha != new_sha,
        "restarted_via": restarted if restarted != "no" else None,
        "restart_log_tail": restart_log.splitlines()[-10:] if restart_log else [],
        "truncated_output": truncated,
        "elapsed_ms": elapsed_ms,
        "next_steps": [
            "Wait ~15s for the marznode service to come back up.",
            "Call verify_panel_certificate to confirm match=true.",
            "Call get_node_info to confirm status=healthy.",
            "If still detached, call get_node_recent_errors for the "
            "next failure layer (e.g. SQL timeout in 'sync').",
        ],
    }


# Silence the unused-import warning — `upload_and_run_script` and
# `run_commands_with_creds` are kept for symmetry with future tools
# that will reuse the same SFTP+exec pattern; the body above currently
# uses the lower-level helpers directly.
_ = (upload_and_run_script, run_commands_with_creds)


# =============================================================================
# 2. Onboard new node from donor — orchestration macro
# =============================================================================


@register_tool(
    name="onboard_node_from_donor",
    description=(
        "End-to-end 'make node B look exactly like node A' macro — "
        "the single confirmation that replaces the admin's manual "
        "onboarding checklist. Runs, in order:\n"
        " (1) preflight: both nodes are in the panel registry,\n"
        " (2) clone_node_config: donor's xray JSON is shipped to "
        "target and xray is restarted; the panel's `_sync()` then "
        "refreshes the target's inbound rows in the DB,\n"
        " (3) regenerate_reality_keys_on_node on TARGET: rotate "
        "reality private_key + short_ids per inbound so the new "
        "node has its own keys (skip with "
        "`regenerate_reality_keys=false` if the admin explicitly "
        "wants the donor's keys preserved across nodes),\n"
        " (4) propagate_node_to_services: every service that "
        "contained any donor inbound now also contains the target's "
        "matching inbound (by tag),\n"
        " (5) clone_donor_hosts_to_target: every donor host is "
        "cloned onto the target's matching inbound with `address` "
        "set to `host_address_override` (or `nodes.address` of "
        "target by default), `remark` rendered from "
        "`host_remark_pattern` (supports `{donor_remark}`, "
        "`{target_name}`, `{target_address}`, `{tag}` placeholders; "
        "empty pattern = donor remark unchanged), and reality keys "
        "swapped to the freshly rotated values from step 3 "
        "(skip with `clone_hosts=false`),\n"
        " (6) resync_node_users: push the full user set onto target "
        "xray,\n"
        " (6.5) post_deploy_gate: run `verify_inbound_e2e` for every "
        "target inbound (panel ↔ xray ↔ marznode push, no external "
        "probe). Records per-tag failures in `failures[]` but does "
        "NOT abort the macro — the admin sees the full report and "
        "applies the per-failure remedy. The most common gate "
        "failure is `panel_service_binding`, fixed by re-running "
        "`propagate_node_to_services(bind_orphan_target_inbounds="
        "true)`.\n"
        " (7) optional `verify_subscription` on `sample_username` — "
        "checks the user's generated subscription contains the "
        "target address.\n"
        "Returns a per-step `steps` report — every step has `name`, "
        "`ok`, and step-specific fields. Stops at the first hard "
        "failure and reports it in `failed_step`. "
        "Does NOT install panel TLS certs — that is "
        "`install_panel_certificate_on_node`, only call it if "
        "`verify_panel_certificate` actually returned `match=false`. "
        "Requires confirmation (mutates services + hosts + restarts "
        "xray on target)."
    ),
    requires_confirmation=True,
)
async def onboard_node_from_donor(
    db: Session,
    donor_node_id: int,
    target_node_id: int,
    sample_username: str = "",
    backend: str = "xray",
    regenerate_reality_keys: bool = True,
    clone_hosts: bool = True,
    host_address_override: str = "",
    host_remark_pattern: str = "",
) -> dict:
    import json

    from app.ai.tools.node_clone_tools import (
        clone_donor_hosts_to_target,
        regenerate_reality_keys_on_node,
    )
    from app.db import crud
    from app.db.models import Inbound
    from app.db.models.core import User
    from app.marznode import node_registry
    from app.utils.share import generate_subscription

    if donor_node_id == target_node_id:
        return {"error": "donor and target must differ"}

    steps: list[dict] = []
    failed_step: Optional[str] = None

    def _step(name: str, **payload) -> dict:
        entry = {"name": name, **payload}
        steps.append(entry)
        return entry

    donor_row = crud.get_node_by_id(db, donor_node_id)
    target_row = crud.get_node_by_id(db, target_node_id)
    if not donor_row:
        return {"error": f"Donor node {donor_node_id} not found"}
    if not target_row:
        return {"error": f"Target node {target_node_id} not found"}
    donor_name = donor_row.name
    target_name = target_row.name
    target_address = target_row.address

    # ----- step 1: connectivity preconditions ----------------------------
    donor_node = node_registry.get(donor_node_id)
    target_node = node_registry.get(target_node_id)
    step1 = _step(
        "preflight",
        donor_connected=donor_node is not None,
        target_connected=target_node is not None,
        donor_status=str(donor_row.status),
        target_status=str(target_row.status),
        target_address=target_address,
        ok=(donor_node is not None and target_node is not None),
    )
    if not step1["ok"]:
        failed_step = "preflight"
        return {
            "donor_node_id": donor_node_id,
            "donor_name": donor_name,
            "target_node_id": target_node_id,
            "target_name": target_name,
            "success": False,
            "failed_step": failed_step,
            "steps": steps,
            "hint": (
                "Both nodes must be connected (panel sees them in "
                "its in-memory registry) before cloning. The "
                "deterministic fix for a node that is missing from "
                "the registry is `enable_node(node_id)` — it forces "
                "the panel to re-instantiate the gRPC client. Only "
                "if `enable_node` does not bring the node up should "
                "you switch to the `diagnose-node-down` skill."
            ),
        }

    db.close()

    # ----- step 2: clone xray config -------------------------------------
    try:
        config, config_format = await donor_node.get_backend_config(name=backend)
    except Exception as exc:
        _step("clone_node_config", ok=False, error=f"read donor: {exc}")
        return {"success": False, "failed_step": "clone_node_config", "steps": steps}
    try:
        await target_node.restart_backend(
            name=backend, config=config, config_format=int(config_format)
        )
    except Exception as exc:
        _step(
            "clone_node_config",
            ok=False,
            error=f"apply on target: {exc}",
            config_size=len(config) if config else 0,
        )
        return {"success": False, "failed_step": "clone_node_config", "steps": steps}
    _step(
        "clone_node_config",
        ok=True,
        backend=backend,
        config_size_bytes=len(config) if config else 0,
    )

    # ----- step 2.5: rotate reality keys per-node on TARGET --------------
    # By default we give the target its own reality private_key /
    # short_ids — so leak of one node's key does not compromise the
    # donor or its siblings. Skip with regenerate_reality_keys=False
    # if the admin explicitly wants the donor's keys preserved.
    rotated_overrides: list[dict] = []
    if regenerate_reality_keys:
        regen_result = await regenerate_reality_keys_on_node(
            db=db, node_id=target_node_id, backend=backend
        )
        if regen_result.get("error"):
            _step(
                "regenerate_reality_keys_on_node",
                ok=False,
                error=regen_result["error"],
            )
            return {
                "success": False,
                "failed_step": "regenerate_reality_keys_on_node",
                "steps": steps,
                "hint": (
                    "Reality key rotation failed AFTER xray was "
                    "already restarted with the donor's config. "
                    "Target is currently running with the donor's "
                    "keys. Re-run this macro with "
                    "regenerate_reality_keys=False to skip rotation, "
                    "or call regenerate_reality_keys_on_node "
                    "directly once the underlying issue is fixed."
                ),
            }
        rotated_overrides = regen_result.get("regenerated") or []
        _step(
            "regenerate_reality_keys_on_node",
            ok=True,
            rotated_inbound_count=len(rotated_overrides),
            rotated_inbound_tags=[r["tag"] for r in rotated_overrides],
            skipped=regen_result.get("skipped") or [],
        )
    else:
        _step(
            "regenerate_reality_keys_on_node",
            ok=True,
            skipped=True,
            note=(
                "regenerate_reality_keys=False — target keeps "
                "donor's reality keys. Cloned hosts will embed "
                "donor pbk/sids."
            ),
        )

    # ----- step 3: propagate inbounds to services ------------------------
    from app.db import GetDB
    from app.ai.tools.service_tools import propagate_node_to_services

    propagation_payload: dict
    try:
        with GetDB() as db2:
            propagation_result = await propagate_node_to_services(
                db=db2,
                from_node_id=donor_node_id,
                to_node_id=target_node_id,
                bind_orphan_target_inbounds=True,
            )
        if propagation_result.get("error"):
            _step(
                "propagate_node_to_services",
                ok=False,
                error=propagation_result["error"],
            )
            return {
                "success": False,
                "failed_step": "propagate_node_to_services",
                "steps": steps,
            }
        propagation_payload = {
            "ok": True,
            "donor_inbound_tags": propagation_result.get("donor_inbound_tags") or [],
            "target_inbound_tags": propagation_result.get("target_inbound_tags") or [],
            "unmatched_donor_tags": propagation_result.get("unmatched_donor_tags") or [],
            "services_updated_count": len(propagation_result.get("services_updated") or []),
            "services_already_up_to_date_count": len(
                propagation_result.get("services_already_up_to_date") or []
            ),
            "services_updated_sample": (
                propagation_result.get("services_updated") or []
            )[:10],
            "orphan_target_inbounds_bound": (
                propagation_result.get("orphan_target_inbounds_bound") or []
            ),
            "orphan_target_inbounds_skipped": (
                propagation_result.get("orphan_target_inbounds_skipped") or []
            ),
        }
    except Exception as exc:
        _step("propagate_node_to_services", ok=False, error=str(exc))
        return {
            "success": False,
            "failed_step": "propagate_node_to_services",
            "steps": steps,
        }
    _step("propagate_node_to_services", **propagation_payload)
    if propagation_payload.get("unmatched_donor_tags"):
        # Soft warning — still continue, but flag it loudly.
        _step(
            "propagate_warning",
            ok=True,
            unmatched_donor_tags=propagation_payload["unmatched_donor_tags"],
            note=(
                "Donor had tags that target's xray config does not "
                "expose — services using those tags will NOT include "
                "the new node. Inspect get_node_config on both, fix "
                "tag drift, then re-run propagate_node_to_services."
            ),
        )

    # ----- step 3.5: clone donor hosts onto target inbounds --------------
    if clone_hosts:
        with GetDB() as db_hosts:
            host_clone_result = await clone_donor_hosts_to_target(
                db=db_hosts,
                donor_node_id=donor_node_id,
                target_node_id=target_node_id,
                host_address_override=host_address_override,
                remark_pattern=host_remark_pattern,
                reality_overrides_json=(
                    json.dumps(rotated_overrides, ensure_ascii=False)
                    if rotated_overrides
                    else ""
                ),
                services_inherit=True,
                delete_placeholder_hosts=True,
            )
        if host_clone_result.get("error"):
            _step(
                "clone_donor_hosts_to_target",
                ok=False,
                error=host_clone_result["error"],
            )
            return {
                "success": False,
                "failed_step": "clone_donor_hosts_to_target",
                "steps": steps,
                "hint": (
                    "Host cloning failed. Inbounds are already "
                    "attached to services, but subscriptions for "
                    "those services will only show placeholder "
                    "hosts on the target until clone_donor_hosts_"
                    "to_target succeeds. Re-run it standalone once "
                    "the underlying issue is fixed."
                ),
            }
        _step(
            "clone_donor_hosts_to_target",
            ok=True,
            target_address_used=host_clone_result.get("target_address_used"),
            created_hosts_count=len(host_clone_result.get("created_hosts") or []),
            created_hosts_sample=(host_clone_result.get("created_hosts") or [])[:10],
            skipped_donor_hosts=host_clone_result.get("skipped_donor_hosts") or [],
            unmatched_donor_tags=host_clone_result.get("unmatched_donor_tags") or [],
            deleted_placeholder_host_ids=(
                host_clone_result.get("deleted_placeholder_host_ids") or []
            ),
        )
    else:
        _step(
            "clone_donor_hosts_to_target",
            ok=True,
            skipped=True,
            note=(
                "clone_hosts=False — only the panel-default "
                "placeholder hosts will represent target's "
                "inbounds in subscriptions. Create real hosts by "
                "hand or re-run with clone_hosts=True."
            ),
        )

    # ----- step 4: resync users on target --------------------------------
    try:
        await target_node.resync_users()
        _step("resync_node_users", ok=True)
    except Exception as exc:
        _step("resync_node_users", ok=False, error=str(exc))
        return {
            "success": False,
            "failed_step": "resync_node_users",
            "steps": steps,
            "hint": (
                "Resync failed — common cause is the panel's "
                "SQLALCHEMY_STATEMENT_TIMEOUT being too low for the "
                "user count on this node. Raise it in the panel .env "
                "(60-120s) and restart the panel container, then "
                "retry. Also check get_node_recent_errors."
            ),
        }

    # ----- step 4.5: post-deploy gate ------------------------------------
    # Run verify_inbound_e2e for every target inbound. This catches the
    # silent failure modes the macro used to miss: orphan inbounds with
    # 0 service bindings (xray running, 0 clients pushed), reality key
    # drift, port mismatches between hosts and xray, firewall blocking
    # the xray port. Failures here are reported as `gate_failures` but
    # do NOT abort the macro — the admin needs the full report to know
    # what to fix manually.
    from app.ai.tools.node_verify_tools import verify_inbound_e2e

    gate_failures: list[dict] = []
    gate_passes: list[dict] = []
    try:
        with GetDB() as db_gate:
            target_tags = [
                i.tag for i in db_gate.query(Inbound).filter(
                    Inbound.node_id == target_node_id
                ).all()
            ]
        for tag in target_tags:
            with GetDB() as db_one:
                report = await verify_inbound_e2e(
                    db=db_one,
                    node_id=target_node_id,
                    inbound_tag=tag,
                    backend=backend,
                    external_probe=False,
                )
            entry = {
                "inbound_tag": tag,
                "ok": bool(report.get("ok")),
                "failed_checks": [
                    {"name": c.get("name"), "remedy": c.get("remedy")}
                    for c in (report.get("checks") or [])
                    if not c.get("ok", True)
                ],
            }
            if entry["ok"]:
                gate_passes.append({"inbound_tag": tag})
            else:
                gate_failures.append(entry)
    except Exception as exc:
        _step("post_deploy_gate", ok=False, error=str(exc))
        return {
            "success": False,
            "failed_step": "post_deploy_gate",
            "steps": steps,
            "hint": (
                "Post-deploy verification crashed unexpectedly. "
                "Re-run `verify_inbound_e2e` per tag manually."
            ),
        }
    _step(
        "post_deploy_gate",
        ok=not gate_failures,
        passed_inbound_count=len(gate_passes),
        failed_inbound_count=len(gate_failures),
        failures=gate_failures[:20],
        hint=(
            None
            if not gate_failures
            else (
                "Some target inbounds failed end-to-end verification. "
                "Read each failure's `failed_checks[].remedy` and "
                "apply the fix it suggests. Most common: "
                "`panel_service_binding` failure → re-run "
                "`propagate_node_to_services` with "
                "`bind_orphan_target_inbounds=true`."
            )
        ),
    )
    if gate_failures:
        failed_step = "post_deploy_gate"

    # ----- step 5: subscription verification -----------------------------
    sample = (sample_username or "").strip()
    if not sample:
        _step("verify_subscription", skipped=True, ok=True)
    else:
        try:
            with GetDB() as db3:
                user = (
                    db3.query(User).filter(User.username == sample).first()
                )
                if not user:
                    _step(
                        "verify_subscription",
                        ok=False,
                        error=f"user {sample!r} not found",
                    )
                else:
                    payload = generate_subscription(
                        user=user, config_format="links"
                    )
                    lines = [
                        ln.strip()
                        for ln in (payload or "").splitlines()
                        if ln.strip()
                    ]
                    addr = (target_address or "").lower()
                    matches = [ln for ln in lines if addr and addr in ln.lower()]
                    _step(
                        "verify_subscription",
                        ok=bool(matches),
                        sample_username=sample,
                        total_lines=len(lines),
                        match_in_subscription=bool(matches),
                        matched_lines_count=len(matches),
                    )
        except Exception as exc:
            _step("verify_subscription", ok=False, error=str(exc))

    return {
        "donor_node_id": donor_node_id,
        "donor_name": donor_name,
        "target_node_id": target_node_id,
        "target_name": target_name,
        "success": all(s.get("ok", True) for s in steps),
        "failed_step": failed_step,
        "steps": steps,
    }
