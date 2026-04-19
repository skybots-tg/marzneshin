"""AI tools for TLS+landing+gRPC provisioning on a node.

This module exposes six tools that, together, let the agent take a
fresh marznode-only node and — in one approval — turn it into a node
that:

1. has a real Let's Encrypt certificate for the admin's chosen domain,
2. serves a believable static landing page on plain HTTPS hits,
3. exposes a VLESS+gRPC inbound to Xray over a unix domain socket
   (Caddy terminates TLS and reverse-proxies under `/<service>/*`),
4. has a universal panel host pointing at the new endpoint so users'
   subscriptions immediately include it.

Architecture choice (see chat with the admin): Caddy fronts everything
on 80/443. Xray listens on a UDS (no public 443 conflict). HTTP-01 is
the only ACME method (port 80 must be reachable from LE). The bundled
landings live in `app/ai/templates/landings/<key>/index.html`.

State persisted to the panel DB lives in `node_tls_provisioning` —
domain, template, cert dates — so `tls_status` can answer without an
SSH round-trip.

All write tools require_confirmation=True and require the chat session
to be SSH-unlocked and per-node credentials saved (same pattern as
`node_provision_tools.install_panel_certificate_on_node`).
"""
from __future__ import annotations

import asyncio
import io
import ipaddress
import json
import logging
import re
import socket
from datetime import datetime
from typing import Optional

import paramiko
from sqlalchemy.orm import Session

from app.ai.landing_templates import (
    LANDING_TEMPLATES,
    get_template,
    render_landing_html,
    template_keys,
)
from app.ai.session_context import get_current_session_id
from app.ai.ssh_runner import (
    _exec_with_caps,
    _open_ssh,
    decrypt_node_credentials,
)
from app.ai.ssh_session import (
    SSH_UNLOCK_TTL_SEC,
    get_unlocked_pin,
    is_session_unlocked,
)
from app.ai.tool_registry import register_tool
from app.db import GetDB, crud

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Constants — the AI tools are the only sane place to centralise these
# because the bash script consumes them positionally and the panel host
# row needs them to render subscriptions correctly.
# ----------------------------------------------------------------------

DEFAULT_GRPC_SERVICE = "grpc"
DEFAULT_UDS_PATH = "/var/run/xray-grpc.sock"
DEFAULT_HTTPS_PORT = 443
DEFAULT_HTTP_PORT = 80
DEFAULT_XRAY_INBOUND_TAG = "vless-grpc-tls"

PROVISION_SCRIPT_REMOTE_PATH = "/tmp/marzneshin_provision_tls.sh"
UNINSTALL_SCRIPT_REMOTE_PATH = "/tmp/marzneshin_uninstall_tls.sh"
LANDING_REMOTE_DIR = "/tmp/marzneshin_landing"
LANDING_REMOTE_INDEX = f"{LANDING_REMOTE_DIR}/index.html"

PROVISION_SCRIPT_LOCAL = "provision_tls.sh"
UNINSTALL_SCRIPT_LOCAL = "uninstall_tls.sh"

CADDY_CONNECT_TIMEOUT_SEC = 30
PROVISION_RUN_TIMEOUT_SEC = 240
UNINSTALL_RUN_TIMEOUT_SEC = 60
RENEW_RUN_TIMEOUT_SEC = 60
DNS_LOOKUP_TIMEOUT_SEC = 5

DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)"
    r"(?:\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))+$"
)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _load_creds_for(node_id: int) -> Optional[dict]:
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


def _ssh_locked_response(node_id: int) -> dict:
    return {
        "error": (
            "SSH is not unlocked for this chat session, or per-node "
            "credentials are missing. Call ssh_check_access first; the "
            "UI will prompt the admin for PIN/credentials."
        ),
        "code": "SSH_LOCKED",
        "node_id": node_id,
        "unlock_ttl_seconds": SSH_UNLOCK_TTL_SEC,
    }


def _split_marker_sections(stdout: str) -> dict[str, list[str]]:
    """Group lines under the most recent `### NAME` header.

    The provisioner outputs multi-line sections (cert info, journalctl
    tails, etc.) so we keep them as lists rather than joining.
    """
    sections: dict[str, list[str]] = {}
    current = None
    for raw in stdout.splitlines():
        if raw.startswith("### "):
            current = raw[4:].strip()
            sections.setdefault(current, [])
        elif current is not None:
            sections[current].append(raw)
    return sections


def _parse_kv_lines(lines: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for ln in lines:
        if "=" in ln:
            k, v = ln.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _parse_openssl_date(raw: str) -> Optional[datetime]:
    if not raw:
        return None
    fmt = "%b %d %H:%M:%S %Y %Z"
    try:
        return datetime.strptime(raw.strip(), fmt)
    except ValueError:
        return None


def _validate_domain(domain: str) -> Optional[str]:
    if not domain or not isinstance(domain, str):
        return "domain must be a non-empty string"
    if not DOMAIN_RE.match(domain):
        return f"domain {domain!r} does not look like a valid hostname"
    return None


def _validate_email(email: str) -> Optional[str]:
    if not email or not EMAIL_RE.match(email):
        return f"contact_email {email!r} is not a valid email address"
    return None


def _resolve_domain(domain: str) -> dict:
    """Best-effort DNS A/AAAA lookup with a short timeout.

    We can't enforce a per-call timeout on `socket.getaddrinfo` reliably
    across platforms, so we set the default socket timeout for the
    duration of the call. The result includes both v4 and v6 addresses
    so the caller can compare against the node's reported address (which
    can itself be either family).
    """
    prev_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(DNS_LOOKUP_TIMEOUT_SEC)
    try:
        infos = socket.getaddrinfo(
            domain, None, type=socket.SOCK_STREAM
        )
    except socket.gaierror as exc:
        return {"resolved": False, "error": f"DNS lookup failed: {exc}"}
    except OSError as exc:
        return {"resolved": False, "error": f"DNS error: {exc}"}
    finally:
        socket.setdefaulttimeout(prev_timeout)

    addrs: list[str] = []
    for family, _stype, _proto, _canon, sockaddr in infos:
        if family == socket.AF_INET:
            addrs.append(sockaddr[0])
        elif family == socket.AF_INET6:
            addrs.append(sockaddr[0])
    return {"resolved": True, "addresses": sorted(set(addrs))}


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


# ----------------------------------------------------------------------
# Xray inbound patcher — best-effort, idempotent.
# ----------------------------------------------------------------------


def _build_grpc_inbound(uds_path: str, service_name: str, tag: str) -> dict:
    return {
        "tag": tag,
        "listen": f"{uds_path},0666",
        "protocol": "vless",
        "settings": {"clients": [], "decryption": "none"},
        "streamSettings": {
            "network": "grpc",
            "security": "none",
            "grpcSettings": {"serviceName": service_name},
        },
        "sniffing": {
            "enabled": True,
            "destOverride": ["http", "tls", "quic"],
        },
    }


def _patch_xray_config(
    raw_json: str,
    *,
    uds_path: str,
    service_name: str,
    tag: str,
) -> tuple[Optional[str], Optional[str], bool]:
    """Append the gRPC inbound if not present.

    Returns `(new_json, error, changed)`. `error` is non-None when the
    existing config is shaped in a way we refuse to touch (parse error,
    or inbound with the same tag but different settings).
    """
    try:
        cfg = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        return None, f"existing xray config is not valid JSON: {exc}", False
    if not isinstance(cfg, dict):
        return None, "existing xray config is not a JSON object", False

    inbounds = cfg.get("inbounds")
    if not isinstance(inbounds, list):
        return None, "xray config has no `inbounds` list", False

    new_inbound = _build_grpc_inbound(uds_path, service_name, tag)

    for existing in inbounds:
        if not isinstance(existing, dict):
            continue
        if existing.get("tag") != tag:
            continue
        if (
            existing.get("listen") == new_inbound["listen"]
            and existing.get("protocol") == "vless"
            and (existing.get("streamSettings") or {}).get("network") == "grpc"
            and (
                (existing.get("streamSettings") or {}).get("grpcSettings") or {}
            ).get("serviceName") == service_name
        ):
            return raw_json, None, False
        return None, (
            f"inbound with tag {tag!r} already exists with different "
            "settings. Refuse to overwrite — rename the existing tag or "
            "remove it manually, then retry."
        ), False

    inbounds.append(new_inbound)
    return json.dumps(cfg, indent=2), None, True


# ----------------------------------------------------------------------
# Tool 1 — readonly readiness check
# ----------------------------------------------------------------------


@register_tool(
    name="tls_check_readiness",
    description=(
        "Read-only preflight before tls_provision. Verifies that "
        "(a) the supplied domain looks valid, "
        "(b) DNS A/AAAA records for the domain resolve to the node's "
        "public address (so Let's Encrypt HTTP-01 can succeed), "
        "(c) per-node SSH credentials are saved and the chat session "
        "is SSH-unlocked, "
        "(d) ports 80 and 443 are not already taken by another "
        "service on the node (best-effort `ss -ltn` check; only run "
        "when SSH is available). "
        "Returns a `ready` boolean and a list of `blockers` with "
        "human-readable hints. ALWAYS call this first — burning a "
        "Let's Encrypt issuance attempt with bad DNS counts against "
        "the per-domain rate limit."
    ),
    requires_confirmation=False,
)
async def tls_check_readiness(
    db: Session,
    node_id: int,
    domain: str,
) -> dict:
    node = crud.get_node_by_id(db, node_id)
    if not node:
        return {"error": f"Node {node_id} not found"}
    node_address = node.address
    blockers: list[str] = []
    warnings: list[str] = []

    domain_err = _validate_domain(domain)
    if domain_err:
        blockers.append(domain_err)

    dns = (
        await asyncio.to_thread(_resolve_domain, domain)
        if not domain_err
        else {"resolved": False, "error": "skipped (invalid domain)"}
    )
    addresses = dns.get("addresses", []) if dns.get("resolved") else []
    dns_matches: Optional[bool] = None
    if dns.get("resolved"):
        if _is_ip(node_address):
            dns_matches = node_address in addresses
        else:
            dns_matches = None
            warnings.append(
                "node.address is a hostname, not an IP — cannot "
                "compare DNS automatically. Make sure both names "
                "resolve to the same public IP."
            )
        if dns_matches is False:
            blockers.append(
                f"DNS A/AAAA for {domain!r} resolves to "
                f"{addresses or '[]'} but node address is "
                f"{node_address!r}. Update the DNS record before "
                "provisioning, or Let's Encrypt HTTP-01 will fail."
            )
    elif not domain_err:
        blockers.append(f"DNS lookup failed: {dns.get('error')}")

    pin_hash = crud.get_ssh_pin_hash(db)
    creds_row = crud.get_ssh_credentials(db, node_id)
    session_id = get_current_session_id()
    pin_configured = pin_hash is not None
    credentials_saved = creds_row is not None
    session_unlocked = bool(session_id) and is_session_unlocked(session_id)
    if not pin_configured:
        blockers.append("Global SSH PIN is not set — admin must configure it once.")
    if not credentials_saved:
        blockers.append(
            f"No SSH credentials saved for node {node_id}. The admin "
            "must store ssh_user / ssh_password (or ssh_key) via the "
            "panel UI."
        )
    if not session_unlocked:
        blockers.append(
            "This chat session is not SSH-unlocked. The admin must "
            "enter the PIN in the dialog."
        )

    ports_check: dict = {"checked": False}
    if pin_configured and credentials_saved and session_unlocked:
        creds = _load_creds_for(node_id)
        if creds is None:
            blockers.append(
                "Failed to decrypt stored credentials with the "
                "unlocked PIN — the credentials may have been "
                "re-encrypted with a different PIN."
            )
        else:
            try:
                ports_check = await asyncio.to_thread(
                    _ssh_check_ports, node_address, creds
                )
            except Exception as exc:
                logger.warning("port preflight failed: %s", exc)
                ports_check = {"checked": False, "error": str(exc)}
            if ports_check.get("checked"):
                taken = ports_check.get("taken_ports", [])
                if taken:
                    blockers.append(
                        f"Ports already in use on node: {taken}. "
                        "Free 80 and 443 (stop nginx/apache or move "
                        "Xray off TCP 443) before provisioning."
                    )

    return {
        "node_id": node_id,
        "node_name": node.name,
        "node_address": node_address,
        "domain": domain,
        "dns": {
            "resolved": dns.get("resolved", False),
            "addresses": addresses,
            "matches_node_address": dns_matches,
            "error": dns.get("error"),
        },
        "ssh": {
            "pin_configured": pin_configured,
            "credentials_saved": credentials_saved,
            "session_unlocked": session_unlocked,
        },
        "ports": ports_check,
        "ready": not blockers,
        "blockers": blockers,
        "warnings": warnings,
    }


def _ssh_check_ports(host: str, creds: dict) -> dict:
    """Run a single `ss -ltn` over SSH and parse listening ports.

    Returns `taken_ports` containing 80 / 443 if any TCP listener is
    bound to them. On any failure returns `checked: False` with an
    error string — the caller treats this as advisory only.
    """
    client: Optional[paramiko.SSHClient] = None
    try:
        client = _open_ssh(host, creds, CADDY_CONNECT_TIMEOUT_SEC)
        exit_code, stdout, _stderr, _trunc = _exec_with_caps(
            client, "ss -ltn 2>/dev/null || netstat -ltn 2>/dev/null", 15
        )
    except paramiko.AuthenticationException as exc:
        return {"checked": False, "error": f"auth: {exc}"}
    except (paramiko.SSHException, OSError) as exc:
        return {"checked": False, "error": f"ssh: {exc}"}
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass

    if exit_code != 0:
        return {"checked": False, "error": f"exit_code={exit_code}"}

    taken: list[int] = []
    for line in stdout.splitlines():
        for port in (DEFAULT_HTTP_PORT, DEFAULT_HTTPS_PORT):
            if f":{port} " in line or line.endswith(f":{port}"):
                if port not in taken:
                    taken.append(port)
    return {"checked": True, "taken_ports": sorted(taken)}


# ----------------------------------------------------------------------
# Tool 2 — list landing templates (no SSH required)
# ----------------------------------------------------------------------


@register_tool(
    name="tls_list_landing_templates",
    description=(
        "Return the catalogue of bundled landing-page templates that "
        "tls_provision can deploy. Each entry has a stable `key` "
        "(use it as the `landing_template` argument), a short `title` "
        "and a longer `description` of what the page looks like. "
        "All templates are static HTML stubs styled to look like "
        "real online file-converter products — the upload widget "
        "always falls through to a generic 'service temporarily "
        "unavailable' toast. Use this to recommend a template to the "
        "admin before calling tls_provision."
    ),
    requires_confirmation=False,
)
async def tls_list_landing_templates(db: Session) -> dict:
    return {
        "templates": [
            {
                "key": t.key,
                "title": t.title,
                "description": t.description,
            }
            for t in LANDING_TEMPLATES
        ],
        "default": LANDING_TEMPLATES[0].key,
        "total": len(LANDING_TEMPLATES),
    }


# ----------------------------------------------------------------------
# Tool 3 — provisioner (heavy)
# ----------------------------------------------------------------------


@register_tool(
    name="tls_provision",
    description=(
        "DESTRUCTIVE end-to-end TLS provisioner. Installs Caddy as a "
        "single binary on the node, writes a Caddyfile that "
        "terminates TLS for `domain` via Let's Encrypt HTTP-01 (port "
        "80 must be reachable from the public internet), serves the "
        "selected `landing_template` for plain HTTPS hits, and "
        "reverse-proxies requests under `/<grpc_service_name>/*` "
        "(default `grpc`) over HTTP/2 cleartext to a unix socket "
        f"(default `{DEFAULT_UDS_PATH}`). After Caddy is up, the "
        "tool patches the node's Xray config to add a VLESS+gRPC "
        "inbound listening on that socket (tag "
        f"`{DEFAULT_XRAY_INBOUND_TAG}`, no clients — marznode adds "
        "users on its own), restarts Xray, and creates a UNIVERSAL "
        "panel host pointing at `<domain>:443` with network=grpc, "
        "security=tls so all services include the new endpoint in "
        "their subscriptions automatically. State (domain, template, "
        "cert dates) is persisted in `node_tls_provisioning`. "
        "Idempotent: re-running with the same args reloads Caddy "
        "without losing the cert and refreshes the host row.\n\n"
        "Preconditions: ssh_check_access=ready, tls_check_readiness="
        "ready (DNS pointed at the node, ports 80/443 free). Skipping "
        "the readiness check risks burning Let's Encrypt rate limits.\n\n"
        "Returns a per-step report (`steps`), the issued cert's "
        "validity window (`cert_not_before`, `cert_not_after`), the "
        "created `host_id`, and a `next_steps` checklist."
    ),
    requires_confirmation=True,
)
async def tls_provision(
    db: Session,
    node_id: int,
    domain: str,
    contact_email: str,
    landing_template: str = "",
    grpc_service_name: str = DEFAULT_GRPC_SERVICE,
    uds_path: str = DEFAULT_UDS_PATH,
    also_patch_xray: bool = True,
    create_panel_host: bool = True,
) -> dict:
    domain = (domain or "").strip().lower()
    contact_email = (contact_email or "").strip()
    landing_template = (landing_template or LANDING_TEMPLATES[0].key).strip()
    grpc_service_name = (grpc_service_name or DEFAULT_GRPC_SERVICE).strip() or DEFAULT_GRPC_SERVICE
    uds_path = (uds_path or DEFAULT_UDS_PATH).strip() or DEFAULT_UDS_PATH

    for err in (
        _validate_domain(domain),
        _validate_email(contact_email),
    ):
        if err:
            return {"error": err, "code": "BAD_ARGS"}

    if landing_template not in template_keys():
        return {
            "error": (
                f"Unknown landing_template {landing_template!r}. "
                f"Valid keys: {list(template_keys())}. Call "
                "tls_list_landing_templates for descriptions."
            ),
            "code": "BAD_ARGS",
        }
    if not re.match(r"^[A-Za-z0-9_-]{1,64}$", grpc_service_name):
        return {
            "error": (
                "grpc_service_name must match [A-Za-z0-9_-]{1,64} so "
                "it slots cleanly into the Caddyfile path matcher."
            ),
            "code": "BAD_ARGS",
        }
    if not uds_path.startswith("/") or "\n" in uds_path or " " in uds_path:
        return {
            "error": "uds_path must be an absolute path with no whitespace.",
            "code": "BAD_ARGS",
        }

    node = crud.get_node_by_id(db, node_id)
    if not node:
        return {"error": f"Node {node_id} not found", "code": "NO_NODE"}
    node_address = node.address
    node_name = node.name

    creds = _load_creds_for(node_id)
    if creds is None:
        return _ssh_locked_response(node_id)

    try:
        landing_html = render_landing_html(landing_template)
    except (KeyError, FileNotFoundError) as exc:
        return {"error": f"Cannot load landing template: {exc}", "code": "TEMPLATE_MISSING"}

    try:
        with open(PROVISION_SCRIPT_LOCAL, "r", encoding="utf-8") as fh:
            script_text = fh.read()
    except OSError as exc:
        return {
            "error": f"Cannot read {PROVISION_SCRIPT_LOCAL}: {exc}",
            "code": "SCRIPT_MISSING",
        }

    db.close()

    steps: list[dict] = []

    def step(name: str, **payload) -> dict:
        entry = {"name": name, **payload}
        steps.append(entry)
        return entry

    try:
        run_result = await asyncio.to_thread(
            _ssh_provision,
            host=node_address,
            creds=creds,
            script_text=script_text,
            landing_html=landing_html,
            domain=domain,
            email=contact_email,
            uds_path=uds_path,
            grpc_service=grpc_service_name,
        )
    except PermissionError as exc:
        return {"error": f"SSH auth failed: {exc}", "code": "AUTH_FAILED"}
    except Exception as exc:
        logger.exception("tls_provision SSH stage failed")
        return {"error": f"SSH execution failed: {exc}", "code": "EXEC_ERROR"}

    sections = run_result["sections"]
    exit_code = run_result["exit_code"]

    cert_section = _parse_kv_lines(sections.get("step_cert", []))
    cert_status = cert_section.get("status")
    cert_not_before = _parse_openssl_date(cert_section.get("not_before", ""))
    cert_not_after = _parse_openssl_date(cert_section.get("not_after", ""))

    step(
        "ssh_run_provisioner",
        ok=(exit_code == 0),
        exit_code=exit_code,
        sections_seen=sorted(sections.keys()),
    )

    fatal = sections.get("fatal", [])
    if exit_code != 0 or fatal:
        return {
            "node_id": node_id,
            "node_name": node_name,
            "success": False,
            "failed_step": "ssh_run_provisioner",
            "exit_code": exit_code,
            "fatal": fatal,
            "stdout_tail": run_result["stdout"].splitlines()[-30:],
            "stderr_tail": run_result["stderr"].splitlines()[-15:],
            "steps": steps,
            "hint": (
                "Caddy installation failed. Common causes: no outbound "
                "internet on the node (download_failed), port 80/443 "
                "already taken (caddy_not_active — see journalctl tail "
                "in stdout), or invalid email. Fix and re-run."
            ),
        }

    step(
        "lets_encrypt",
        ok=(cert_status == "ok"),
        cert_status=cert_status,
        cert_path=cert_section.get("cert_path"),
        not_before=cert_not_before.isoformat() if cert_not_before else None,
        not_after=cert_not_after.isoformat() if cert_not_after else None,
        issuer=cert_section.get("issuer"),
        subject=cert_section.get("subject"),
    )
    if cert_status != "ok":
        return {
            "node_id": node_id,
            "node_name": node_name,
            "success": False,
            "failed_step": "lets_encrypt",
            "steps": steps,
            "hint": (
                "Caddy is running but the certificate did not appear "
                "within 60s. Most often this is a DNS/firewall issue: "
                "make sure 80/tcp from the LE servers reaches the node "
                "and the A record for the domain points at it. Wait a "
                "couple of minutes and call tls_status — if the cert "
                "shows up, you can carry on with also_patch_xray=True "
                "and create_panel_host=True manually."
            ),
        }

    xray_step: dict
    if also_patch_xray:
        xray_step = await _patch_xray_inbound(
            node_id=node_id,
            uds_path=uds_path,
            service_name=grpc_service_name,
            tag=DEFAULT_XRAY_INBOUND_TAG,
        )
        steps.append(xray_step)
        if not xray_step.get("ok"):
            return {
                "node_id": node_id,
                "node_name": node_name,
                "success": False,
                "failed_step": "patch_xray",
                "steps": steps,
                "hint": (
                    "Caddy + cert are good, but adding the VLESS+gRPC "
                    "inbound to Xray failed. Use get_node_config to "
                    "inspect the live config, fix the conflict, then "
                    "either add the inbound by hand or call "
                    "tls_provision again with the same arguments."
                ),
            }

    host_step: dict
    host_id: Optional[int] = None
    if create_panel_host:
        host_step = await asyncio.to_thread(
            _create_universal_grpc_host,
            domain=domain,
            grpc_service=grpc_service_name,
            node_name=node_name,
        )
        steps.append(host_step)
        if host_step.get("ok"):
            host_id = host_step.get("host_id")
        else:
            return {
                "node_id": node_id,
                "node_name": node_name,
                "success": False,
                "failed_step": "create_panel_host",
                "steps": steps,
                "hint": (
                    "Cert and Xray are configured, but the universal "
                    "host could not be created. Inspect the error in "
                    "the step report and add the host manually via "
                    "create_host (network=grpc, security=tls)."
                ),
            }

    persist_step = await asyncio.to_thread(
        _persist_state,
        node_id=node_id,
        domain=domain,
        landing_template=landing_template,
        grpc_service_name=grpc_service_name,
        uds_path=uds_path,
        contact_email=contact_email,
        cert_not_before=cert_not_before,
        cert_not_after=cert_not_after,
    )
    steps.append(persist_step)

    return {
        "node_id": node_id,
        "node_name": node_name,
        "success": True,
        "domain": domain,
        "landing_template": landing_template,
        "grpc_service_name": grpc_service_name,
        "uds_path": uds_path,
        "cert_not_before": cert_not_before.isoformat() if cert_not_before else None,
        "cert_not_after": cert_not_after.isoformat() if cert_not_after else None,
        "host_id": host_id,
        "steps": steps,
        "next_steps": [
            f"Open https://{domain}/ — the landing should render.",
            (
                "Wait ~10s for marznode to resync inbounds, then call "
                "get_node_info to confirm status=healthy."
            ),
            "Generate a subscription for any user and verify the new "
            f"{domain}:443 grpc/tls entry appears.",
        ],
    }


def _ssh_provision(
    *,
    host: str,
    creds: dict,
    script_text: str,
    landing_html: str,
    domain: str,
    email: str,
    uds_path: str,
    grpc_service: str,
) -> dict:
    """SFTP upload landing + script, then exec the script. One SSH conn."""
    client: Optional[paramiko.SSHClient] = None
    try:
        client = _open_ssh(host, creds, CADDY_CONNECT_TIMEOUT_SEC)
        sftp = client.open_sftp()
        try:
            try:
                sftp.mkdir(LANDING_REMOTE_DIR)
            except IOError:
                pass
            sftp.putfo(
                io.BytesIO(landing_html.encode("utf-8")),
                LANDING_REMOTE_INDEX,
            )
            sftp.chmod(LANDING_REMOTE_INDEX, 0o644)

            sftp.putfo(
                io.BytesIO(script_text.encode("utf-8")),
                PROVISION_SCRIPT_REMOTE_PATH,
            )
            sftp.chmod(PROVISION_SCRIPT_REMOTE_PATH, 0o755)
        finally:
            sftp.close()

        cmd = (
            f"bash {PROVISION_SCRIPT_REMOTE_PATH} "
            f"{_sh_quote(domain)} {_sh_quote(email)} "
            f"{_sh_quote(uds_path)} {_sh_quote(grpc_service)} "
            f"{_sh_quote(LANDING_REMOTE_DIR)}"
        )
        exit_code, stdout, stderr, truncated = _exec_with_caps(
            client, cmd, PROVISION_RUN_TIMEOUT_SEC
        )
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass

    return {
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "truncated": truncated,
        "sections": _split_marker_sections(stdout),
    }


def _sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


async def _patch_xray_inbound(
    *,
    node_id: int,
    uds_path: str,
    service_name: str,
    tag: str,
) -> dict:
    """Pull the live Xray JSON from marznode, append our inbound, push back."""
    from app.marznode import node_registry

    node = node_registry.get(node_id)
    if not node:
        return {
            "name": "patch_xray",
            "ok": False,
            "error": (
                "Node is not connected to the panel — cannot read or "
                "restart the backend remotely. Reconnect first."
            ),
        }
    try:
        config, config_format = await node.get_backend_config(name="xray")
    except Exception as exc:
        return {
            "name": "patch_xray",
            "ok": False,
            "error": f"get_backend_config failed: {exc}",
        }
    if not config:
        return {
            "name": "patch_xray",
            "ok": False,
            "error": "node returned empty xray config",
        }

    new_config, err, changed = _patch_xray_config(
        config, uds_path=uds_path, service_name=service_name, tag=tag
    )
    if err:
        return {"name": "patch_xray", "ok": False, "error": err}

    if not changed:
        return {
            "name": "patch_xray",
            "ok": True,
            "changed": False,
            "tag": tag,
            "note": "inbound already present with matching settings",
        }

    try:
        await node.restart_backend(
            name="xray",
            config=new_config,
            config_format=int(config_format) if config_format else 1,
        )
    except Exception as exc:
        return {
            "name": "patch_xray",
            "ok": False,
            "error": f"restart_backend failed: {exc}",
        }

    return {
        "name": "patch_xray",
        "ok": True,
        "changed": True,
        "tag": tag,
        "uds_path": uds_path,
        "service_name": service_name,
    }


def _create_universal_grpc_host(
    *, domain: str, grpc_service: str, node_name: str
) -> dict:
    from app.db.models import InboundHost
    from app.models.proxy import (
        InboundHost as InboundHostModel,
        InboundHostSecurity,
    )

    remark = f"{node_name} · gRPC TLS"
    with GetDB() as db:
        existing = (
            db.query(InboundHost)
            .filter(
                InboundHost.universal == True,  # noqa: E712
                InboundHost.address == domain,
                InboundHost.host_network == "grpc",
            )
            .first()
        )
        if existing:
            existing.remark = remark
            existing.port = DEFAULT_HTTPS_PORT
            existing.sni = domain
            existing.host = domain
            existing.path = grpc_service
            existing.security = InboundHostSecurity.tls
            existing.is_disabled = False
            db.commit()
            return {
                "name": "create_panel_host",
                "ok": True,
                "host_id": existing.id,
                "created": False,
                "remark": remark,
            }

        try:
            host_model = InboundHostModel(
                remark=remark,
                address=domain,
                port=DEFAULT_HTTPS_PORT,
                sni=domain,
                host=domain,
                path=grpc_service,
                security=InboundHostSecurity.tls,
                protocol="vless",
                network="grpc",
                allowinsecure=False,
                is_disabled=False,
                weight=1,
                universal=True,
                service_ids=[],
            )
        except Exception as exc:
            return {
                "name": "create_panel_host",
                "ok": False,
                "error": f"validation: {exc}",
            }
        try:
            db_host = crud.add_host(db, None, host_model)
        except Exception as exc:
            return {
                "name": "create_panel_host",
                "ok": False,
                "error": f"add_host: {exc}",
            }
        return {
            "name": "create_panel_host",
            "ok": True,
            "host_id": db_host.id,
            "created": True,
            "remark": remark,
        }


def _persist_state(
    *,
    node_id: int,
    domain: str,
    landing_template: str,
    grpc_service_name: str,
    uds_path: str,
    contact_email: str,
    cert_not_before: Optional[datetime],
    cert_not_after: Optional[datetime],
) -> dict:
    with GetDB() as db:
        crud.upsert_tls_provisioning(
            db,
            node_id,
            domain=domain,
            landing_template=landing_template,
            grpc_service_name=grpc_service_name,
            uds_path=uds_path,
            contact_email=contact_email,
        )
        crud.update_cert_dates(
            db,
            node_id,
            issued_at=cert_not_before,
            expires_at=cert_not_after,
        )
    return {"name": "persist_state", "ok": True}


# ----------------------------------------------------------------------
# Tool 4 — force renew (caddy reload + re-read cert)
# ----------------------------------------------------------------------


@register_tool(
    name="tls_renew_now",
    description=(
        "Force Caddy to reload its config and re-evaluate certificate "
        "freshness for the node's provisioned domain. Caddy already "
        "auto-renews about 30 days before expiry, so this is mostly "
        "useful when DNS or firewall was just fixed and you want to "
        "confirm renewal works without waiting. Returns the cert's new "
        "validity window if the file is reachable, or the journal "
        "tail if the reload failed. Requires SSH unlocked."
    ),
    requires_confirmation=True,
)
async def tls_renew_now(db: Session, node_id: int) -> dict:
    row = crud.get_tls_provisioning(db, node_id)
    if row is None:
        return {
            "error": (
                "This node has not been provisioned with TLS yet. Call "
                "tls_provision first."
            ),
            "code": "NOT_PROVISIONED",
        }

    node = crud.get_node_by_id(db, node_id)
    if not node:
        return {"error": f"Node {node_id} not found", "code": "NO_NODE"}
    node_address = node.address
    domain = row.domain

    creds = _load_creds_for(node_id)
    if creds is None:
        return _ssh_locked_response(node_id)

    db.close()

    try:
        result = await asyncio.to_thread(
            _ssh_renew, node_address, creds, domain
        )
    except PermissionError as exc:
        return {"error": f"SSH auth failed: {exc}", "code": "AUTH_FAILED"}
    except Exception as exc:
        logger.exception("tls_renew_now failed")
        return {"error": f"SSH execution failed: {exc}", "code": "EXEC_ERROR"}

    crud_updates = {
        "issued_at": _parse_openssl_date(result.get("not_before", "")),
        "expires_at": _parse_openssl_date(result.get("not_after", "")),
    }
    with GetDB() as db2:
        if crud_updates["issued_at"] or crud_updates["expires_at"]:
            crud.update_cert_dates(db2, node_id, **crud_updates)
        else:
            crud.mark_renew_attempted(db2, node_id)

    return {
        "node_id": node_id,
        "domain": domain,
        "reload_ok": result.get("reload_ok"),
        "reload_log_tail": result.get("reload_log_tail", []),
        "cert_path": result.get("cert_path"),
        "not_before": crud_updates["issued_at"].isoformat() if crud_updates["issued_at"] else None,
        "not_after": crud_updates["expires_at"].isoformat() if crud_updates["expires_at"] else None,
        "subject": result.get("subject"),
        "issuer": result.get("issuer"),
    }


def _ssh_renew(host: str, creds: dict, domain: str) -> dict:
    cmd_reload = "systemctl reload caddy 2>&1 | tail -n 30; echo __RC=$?"
    cmd_inspect = (
        "set +e; "
        f"CRT=$(find /var/lib/caddy -type d -name '{domain}' 2>/dev/null | head -n1); "
        f"if [ -n \"$CRT\" ] && [ -f \"$CRT/{domain}.crt\" ]; then "
        "echo \"### path\"; "
        f"echo \"$CRT/{domain}.crt\"; "
        "echo \"### before\"; "
        f"openssl x509 -in \"$CRT/{domain}.crt\" -noout -startdate 2>/dev/null | cut -d= -f2; "
        "echo \"### after\"; "
        f"openssl x509 -in \"$CRT/{domain}.crt\" -noout -enddate 2>/dev/null | cut -d= -f2; "
        "echo \"### subject\"; "
        f"openssl x509 -in \"$CRT/{domain}.crt\" -noout -subject 2>/dev/null | sed 's/^subject= //'; "
        "echo \"### issuer\"; "
        f"openssl x509 -in \"$CRT/{domain}.crt\" -noout -issuer 2>/dev/null | sed 's/^issuer= //'; "
        "echo \"### end\"; "
        "fi"
    )

    client: Optional[paramiko.SSHClient] = None
    try:
        client = _open_ssh(host, creds, CADDY_CONNECT_TIMEOUT_SEC)
        ec1, out1, _err1, _t1 = _exec_with_caps(client, cmd_reload, RENEW_RUN_TIMEOUT_SEC)
        ec2, out2, _err2, _t2 = _exec_with_caps(client, cmd_inspect, 20)
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass

    reload_ok = "__RC=0" in out1
    sections = _split_marker_sections(out2)
    return {
        "reload_ok": reload_ok and ec1 == 0,
        "reload_log_tail": [
            ln for ln in out1.splitlines() if not ln.startswith("__RC=")
        ][-10:],
        "cert_path": (sections.get("path") or [None])[0] if sections.get("path") else None,
        "not_before": (sections.get("before") or [""])[0] if sections.get("before") else "",
        "not_after": (sections.get("after") or [""])[0] if sections.get("after") else "",
        "subject": (sections.get("subject") or [""])[0] if sections.get("subject") else "",
        "issuer": (sections.get("issuer") or [""])[0] if sections.get("issuer") else "",
        "inspect_exit_code": ec2,
    }


# ----------------------------------------------------------------------
# Tool 5 — uninstall (Caddy off, cert wiped, optional host delete)
# ----------------------------------------------------------------------


@register_tool(
    name="tls_uninstall",
    description=(
        "DESTRUCTIVE: stop and remove Caddy + its data + the landing "
        "site root + the cert storage on the node, and clear the "
        "panel-side `node_tls_provisioning` row. The Xray inbound "
        f"with tag `{DEFAULT_XRAY_INBOUND_TAG}` is NOT touched here — "
        "if you also want it gone, edit the Xray config via "
        "update_node_config after this call. The universal host row "
        "matching the provisioned domain is disabled (not deleted) "
        "by default; pass `delete_panel_host=True` to remove it "
        "outright. Requires SSH unlocked."
    ),
    requires_confirmation=True,
)
async def tls_uninstall(
    db: Session,
    node_id: int,
    delete_panel_host: bool = False,
) -> dict:
    row = crud.get_tls_provisioning(db, node_id)
    if row is None:
        return {
            "error": "This node is not provisioned — nothing to uninstall.",
            "code": "NOT_PROVISIONED",
        }

    node = crud.get_node_by_id(db, node_id)
    if not node:
        return {"error": f"Node {node_id} not found", "code": "NO_NODE"}
    node_address = node.address
    domain = row.domain

    creds = _load_creds_for(node_id)
    if creds is None:
        return _ssh_locked_response(node_id)

    try:
        with open(UNINSTALL_SCRIPT_LOCAL, "r", encoding="utf-8") as fh:
            script_text = fh.read()
    except OSError as exc:
        return {
            "error": f"Cannot read {UNINSTALL_SCRIPT_LOCAL}: {exc}",
            "code": "SCRIPT_MISSING",
        }

    db.close()

    try:
        result = await asyncio.to_thread(
            _ssh_uninstall, node_address, creds, script_text
        )
    except PermissionError as exc:
        return {"error": f"SSH auth failed: {exc}", "code": "AUTH_FAILED"}
    except Exception as exc:
        logger.exception("tls_uninstall failed")
        return {"error": f"SSH execution failed: {exc}", "code": "EXEC_ERROR"}

    sections = result["sections"]
    summary = (sections.get("summary") or [""])[0] if sections.get("summary") else ""

    host_action: dict
    host_action = await asyncio.to_thread(
        _cleanup_panel_host, domain, delete_panel_host
    )

    with GetDB() as db2:
        crud.delete_tls_provisioning(db2, node_id)

    return {
        "node_id": node_id,
        "domain": domain,
        "exit_code": result["exit_code"],
        "summary": summary,
        "actions": {
            section: lines
            for section, lines in sections.items()
            if section.startswith("step_")
        },
        "host": host_action,
        "db_state": "removed",
    }


def _ssh_uninstall(host: str, creds: dict, script_text: str) -> dict:
    client: Optional[paramiko.SSHClient] = None
    try:
        client = _open_ssh(host, creds, CADDY_CONNECT_TIMEOUT_SEC)
        sftp = client.open_sftp()
        try:
            sftp.putfo(
                io.BytesIO(script_text.encode("utf-8")),
                UNINSTALL_SCRIPT_REMOTE_PATH,
            )
            sftp.chmod(UNINSTALL_SCRIPT_REMOTE_PATH, 0o755)
        finally:
            sftp.close()
        exit_code, stdout, stderr, truncated = _exec_with_caps(
            client, f"bash {UNINSTALL_SCRIPT_REMOTE_PATH}", UNINSTALL_RUN_TIMEOUT_SEC
        )
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
    return {
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "truncated": truncated,
        "sections": _split_marker_sections(stdout),
    }


def _cleanup_panel_host(domain: str, delete: bool) -> dict:
    from app.db.models import InboundHost

    with GetDB() as db:
        rows = (
            db.query(InboundHost)
            .filter(
                InboundHost.universal == True,  # noqa: E712
                InboundHost.address == domain,
                InboundHost.host_network == "grpc",
            )
            .all()
        )
        if not rows:
            return {"matched": 0, "action": "none"}
        affected = [r.id for r in rows]
        if delete:
            for r in rows:
                db.delete(r)
            db.commit()
            return {"matched": len(rows), "action": "deleted", "ids": affected}
        for r in rows:
            r.is_disabled = True
        db.commit()
        return {"matched": len(rows), "action": "disabled", "ids": affected}


# ----------------------------------------------------------------------
# Tool 6 — status (DB-only by default, optional live SSH check)
# ----------------------------------------------------------------------


@register_tool(
    name="tls_status",
    description=(
        "Return the panel's view of TLS provisioning for a node — "
        "domain, landing template, gRPC service name, cert validity "
        "window, last-renew timestamp. Cheap (DB-only) by default. "
        "Pass `live=True` to additionally SSH into the node and refresh "
        "the cert dates from disk; requires SSH unlocked. Returns "
        "`provisioned=False` when this node has never been through "
        "tls_provision."
    ),
    requires_confirmation=False,
)
async def tls_status(db: Session, node_id: int, live: bool = False) -> dict:
    row = crud.get_tls_provisioning(db, node_id)
    if row is None:
        return {"node_id": node_id, "provisioned": False}

    node = crud.get_node_by_id(db, node_id)
    base = {
        "node_id": node_id,
        "node_name": node.name if node else None,
        "node_address": node.address if node else None,
        "provisioned": True,
        "domain": row.domain,
        "landing_template": row.landing_template,
        "grpc_service_name": row.grpc_service_name,
        "uds_path": row.uds_path,
        "contact_email": row.contact_email,
        "cert_issued_at": row.cert_issued_at.isoformat() if row.cert_issued_at else None,
        "cert_expires_at": row.cert_expires_at.isoformat() if row.cert_expires_at else None,
        "last_renew_attempt_at": (
            row.last_renew_attempt_at.isoformat()
            if row.last_renew_attempt_at
            else None
        ),
        "live_check": None,
    }

    if not live:
        return base

    if not node:
        return base

    creds = _load_creds_for(node_id)
    if creds is None:
        base["live_check"] = {"ok": False, "error": "ssh_locked"}
        return base

    db.close()

    try:
        live_data = await asyncio.to_thread(
            _ssh_renew, node.address, creds, row.domain
        )
    except PermissionError as exc:
        base["live_check"] = {"ok": False, "error": f"auth: {exc}"}
        return base
    except Exception as exc:
        logger.warning("tls_status live check failed: %s", exc)
        base["live_check"] = {"ok": False, "error": str(exc)}
        return base

    not_before = _parse_openssl_date(live_data.get("not_before", ""))
    not_after = _parse_openssl_date(live_data.get("not_after", ""))
    if not_before or not_after:
        with GetDB() as db2:
            crud.update_cert_dates(
                db2, node_id, issued_at=not_before, expires_at=not_after
            )
        if not_before:
            base["cert_issued_at"] = not_before.isoformat()
        if not_after:
            base["cert_expires_at"] = not_after.isoformat()

    base["live_check"] = {
        "ok": True,
        "cert_path": live_data.get("cert_path"),
        "subject": live_data.get("subject"),
        "issuer": live_data.get("issuer"),
    }
    return base
