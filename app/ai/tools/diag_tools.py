import asyncio
import base64
import json
import logging
import re
from urllib.parse import unquote
from uuid import UUID as UUIDType

from sqlalchemy.orm import Session

from app.ai.tool_registry import register_tool
from app.ai.tools._common import clamp_limit, clamp_offset, paginated_envelope

logger = logging.getLogger(__name__)

_SUPPORTED_SUB_FORMATS = {
    "links",
    "xray",
    "sing-box",
    "clash",
    "clash-meta",
}

_MAX_SUB_SNIPPET_BYTES = 30_000


@register_tool(
    name="get_node_logs",
    description="Get recent log lines from a node backend. Useful for diagnosing issues.",
    requires_confirmation=False,
)
async def get_node_logs(db: Session, node_id: int, backend: str = "xray", max_lines: int = 50) -> dict:
    from app.marznode import node_registry
    db.close()
    node = node_registry.get(node_id)
    if not node:
        return {"error": f"Node {node_id} is not connected"}

    lines = []

    async def _collect():
        async for line in node.get_logs(name=backend, include_buffer=True):
            lines.append(line)
            if len(lines) >= max_lines:
                break

    try:
        await asyncio.wait_for(_collect(), timeout=30.0)
    except asyncio.TimeoutError:
        return {
            "error": (
                "Timed out after 30s while reading log stream. "
                "The node may be overloaded or the gRPC stream stalled."
            ),
            "partial_lines": lines,
            "node_id": node_id,
            "backend": backend,
        }
    except asyncio.CancelledError:
        pass
    except Exception as e:
        return {"error": f"Failed to get logs: {str(e)}", "partial_lines": lines}

    return {"node_id": node_id, "backend": backend, "lines": lines, "count": len(lines)}


@register_tool(
    name="check_all_nodes_health",
    description=(
        "Check health status of nodes with pagination. Per-node detail for "
        "the requested page plus an always-accurate summary of healthy / "
        "unhealthy / disabled counts across the full table. Default limit "
        "50, hard max 100. Use `offset` / `next_offset` to walk all nodes "
        "if you have more than one page."
    ),
    requires_confirmation=False,
)
async def check_all_nodes_health(
    db: Session, limit: int = 50, offset: int = 0
) -> dict:
    from app.db.models import Node
    from app.marznode import node_registry

    limit = clamp_limit(limit, default=50, maximum=100)
    offset = clamp_offset(offset)

    total = db.query(Node).count()
    nodes = db.query(Node).order_by(Node.id).offset(offset).limit(limit).all()
    result = []
    for n in nodes:
        connected = node_registry.get(n.id) is not None
        result.append({
            "id": n.id,
            "name": n.name,
            "status": str(n.status),
            "connected": connected,
            "message": n.message,
            "last_status_change": str(n.last_status_change) if n.last_status_change else None,
        })

    from app.models.node import NodeStatus
    healthy_total = db.query(Node).filter(Node.status == NodeStatus.healthy).count()
    unhealthy_total = db.query(Node).filter(Node.status == NodeStatus.unhealthy).count()
    disabled_total = db.query(Node).filter(Node.status == NodeStatus.disabled).count()

    return {
        "nodes": result,
        "summary": {
            "total": total,
            "healthy": healthy_total,
            "unhealthy": unhealthy_total,
            "disabled": disabled_total,
        },
        **paginated_envelope(total, offset, limit),
    }


@register_tool(
    name="get_node_devices",
    description=(
        "Get live connected devices on a node (streamed once from marznode, "
        "not paginated on the node side). Returns every device matching the "
        "filters, then the panel applies `limit` (default 100, hard max 500) "
        "and `offset` in-memory so the agent can still read in pages. "
        "`active_only=True` skips inactive entries. Filters: "
        "`uid_substring` (substring of the marznode UID, typically the "
        "username), `ip_substring` (substring of the remote IP). "
        "Response includes `truncated` and `next_offset` for the next page."
    ),
    requires_confirmation=False,
)
async def get_node_devices(
    db: Session,
    node_id: int,
    active_only: bool = True,
    limit: int = 100,
    offset: int = 0,
    uid_substring: str = "",
    ip_substring: str = "",
) -> dict:
    from app.marznode import node_registry
    db.close()
    node = node_registry.get(node_id)
    if not node:
        return {"error": f"Node {node_id} is not connected"}

    limit = clamp_limit(limit, default=100, maximum=500)
    offset = clamp_offset(offset)

    try:
        response = await node.fetch_all_devices()
    except NotImplementedError:
        return {"error": "This node does not support device listing"}
    except Exception as e:
        return {"error": f"Failed to fetch devices: {str(e)}"}

    all_devices: list[dict] = []
    for user_devices in response.users:
        uid = user_devices.uid
        if uid_substring and uid_substring.lower() not in (uid or "").lower():
            continue
        for device in user_devices.devices:
            if active_only and not device.is_active:
                continue
            if ip_substring and ip_substring not in (device.remote_ip or ""):
                continue
            all_devices.append({
                "uid": uid,
                "remote_ip": device.remote_ip,
                "client_name": device.client_name,
                "protocol": device.protocol if device.protocol else None,
                "is_active": device.is_active,
                "last_seen": str(device.last_seen) if device.last_seen else None,
            })

    total = len(all_devices)
    page = all_devices[offset:offset + limit]

    return {
        "node_id": node_id,
        "devices": page,
        "active_only": active_only,
        **paginated_envelope(total, offset, limit),
    }


@register_tool(
    name="inspect_user_subscription",
    description=(
        "Generate the exact subscription payload a client would receive "
        "for `username` and return it to the agent for analysis — unlike "
        "`get_user_subscription` (which returns only the URL), this one "
        "returns the actual vless/vmess/trojan/ss lines (or xray / "
        "sing-box / clash JSON/YAML) so you can see malformed configs "
        "like `vless://None@` or a missing `security=reality`. "
        "`config_format` is one of: links (default), xray, sing-box, "
        "clash, clash-meta. For `links` each line is a separate proxy. "
        "The payload may contain credentials (UUIDs / passwords / "
        "Reality public keys) — treat it like a secret: use it for "
        "reasoning, do NOT echo the full body into chat unless the "
        "admin explicitly asks. Large payloads are truncated to ~30 KB."
    ),
    requires_confirmation=False,
)
async def inspect_user_subscription(
    db: Session, username: str, config_format: str = "links"
) -> dict:
    from app.db.models.core import User
    from app.models.user import UserResponse
    from app.utils.share import generate_subscription

    fmt = (config_format or "links").lower()
    if fmt not in _SUPPORTED_SUB_FORMATS:
        return {
            "error": (
                f"Unsupported format '{config_format}'. "
                f"Use one of: {sorted(_SUPPORTED_SUB_FORMATS)}"
            )
        }

    db_user = db.query(User).filter(User.username == username).first()
    if not db_user:
        return {"error": f"User '{username}' not found"}
    if db_user.removed:
        return {"error": f"User '{username}' is removed"}

    try:
        user = UserResponse.model_validate(db_user)
        payload = generate_subscription(user=user, config_format=fmt)
    except Exception as exc:
        logger.exception("Failed to generate subscription for %s", username)
        return {"error": f"Failed to generate subscription: {exc}"}

    truncated = False
    if len(payload) > _MAX_SUB_SNIPPET_BYTES:
        payload = payload[:_MAX_SUB_SNIPPET_BYTES]
        truncated = True

    if fmt == "links":
        lines = [ln for ln in payload.splitlines() if ln.strip()]
        return {
            "username": username,
            "config_format": fmt,
            "line_count": len(lines),
            "lines": lines,
            "truncated": truncated,
            "is_active": bool(db_user.is_active),
            "expired": bool(db_user.expired),
            "data_limit_reached": bool(db_user.data_limit_reached),
        }

    return {
        "username": username,
        "config_format": fmt,
        "payload": payload,
        "truncated": truncated,
        "is_active": bool(db_user.is_active),
        "expired": bool(db_user.expired),
        "data_limit_reached": bool(db_user.data_limit_reached),
    }


def _looks_like_reality(host) -> bool:
    """Heuristic: is this host intended to serve Reality?"""
    if host.reality_public_key:
        return True
    if host.flow and "vision" in (host.flow or "").lower():
        # xtls-rprx-vision is almost exclusively used with Reality
        return True
    return False


def _host_protocol(host) -> str:
    return (
        host.inbound.protocol.value
        if host.inbound
        else (host.host_protocol or "")
    ).lower()


def _collect_host_issues(host) -> list[dict]:
    """Return a list of heuristic issues for an InboundHost. Shared between
    `validate_host` (single) and `scan_hosts_for_issues` (bulk)."""
    issues: list[dict] = []

    def add(level: str, field: str | None, message: str) -> None:
        issues.append({"level": level, "field": field, "message": message})

    protocol = _host_protocol(host)

    if not host.address:
        add("error", "address", "address is empty")
    elif "{" in host.address and "}" not in host.address:
        add("warning", "address", "address has an unclosed `{` placeholder")

    port = host.port or 0
    if host.inbound is None and not (1 <= port <= 65535):
        add(
            "error",
            "port",
            "port is missing; for a host without a bound inbound port must "
            "be set explicitly (1-65535)",
        )

    if not host.remark:
        add("error", "remark", "remark is empty")

    if host.inbound is None:
        if protocol == "vless":
            if not host.uuid:
                add(
                    "info",
                    "uuid",
                    "universal VLESS host has no explicit uuid — backend "
                    "will derive per-user uuid from user key (expected "
                    "on builds >= the universal-host fix)",
                )
            if _looks_like_reality(host):
                if not host.reality_public_key:
                    add(
                        "error",
                        "reality_public_key",
                        "Reality/Vision host without reality_public_key — "
                        "clients will receive links with no `pbk=` and "
                        "cannot connect",
                    )
                if not host.reality_short_ids:
                    add(
                        "error",
                        "reality_short_ids",
                        "Reality host without reality_short_ids — clients "
                        "receive links with no `sid=` and are rejected "
                        "by Xray",
                    )
                if not host.sni:
                    add(
                        "error",
                        "sni",
                        "Reality host without sni — generated link will "
                        "have no `sni=`; Xray requires it",
                    )
                fp = host.fingerprint.value if host.fingerprint else ""
                if not fp:
                    add(
                        "warning",
                        "fingerprint",
                        "Reality host with fingerprint=none — most "
                        "clients need `fp=chrome` (or similar) to pass "
                        "DPI",
                    )
            if host.flow and not _looks_like_reality(host):
                add(
                    "warning",
                    "flow",
                    f"flow={host.flow!r} is set but host looks non-"
                    "Reality (no reality_public_key); Vision flow "
                    "without Reality is unusual",
                )
        elif protocol in ("trojan", "shadowsocks", "hysteria2"):
            if not host.password:
                add(
                    "info",
                    "password",
                    f"{protocol} host has no explicit password — "
                    "backend will derive per-user password from user "
                    "key (expected on modern builds)",
                )
        elif not protocol:
            add(
                "error",
                "host_protocol",
                "host has no bound inbound AND no host_protocol — "
                "panel cannot generate any link for it",
            )
    else:
        # Bound-to-inbound host: still check Reality-on-host misconfigs.
        # A VLESS host that HAS reality_public_key set but the field is
        # null/empty is a very common cause of vless://None@ links even
        # when a bound inbound exists, because the reality params are
        # pulled from the host record by `share.py`.
        if protocol == "vless" and _looks_like_reality(host):
            if not host.reality_public_key:
                add(
                    "warning",
                    "reality_public_key",
                    "VLESS host looks like Reality (flow=vision) but "
                    "host-level reality_public_key is empty — link "
                    "will rely entirely on the inbound's reality "
                    "settings; if those are also missing you will "
                    "see `vless://...` without `pbk=`",
                )
            if not host.reality_short_ids:
                add(
                    "warning",
                    "reality_short_ids",
                    "VLESS Reality host without host-level "
                    "reality_short_ids — same caveat as above",
                )

    if (
        getattr(host, "mlkem_enabled", False)
        and not getattr(host, "mlkem_public_key", None)
    ):
        add(
            "error",
            "mlkem_public_key",
            "mlkem_enabled=true but mlkem_public_key is empty",
        )

    if host.is_disabled:
        add(
            "info",
            "is_disabled",
            "host is disabled — it will not appear in any subscription",
        )

    return issues


@register_tool(
    name="validate_host",
    description=(
        "Run a set of heuristic checks on a single host entry and report "
        "misconfigurations that usually cause broken subscriptions — "
        "missing Reality public key on a universal host, empty UUID on a "
        "VLESS host that has no bound inbound, `fingerprint=none` on a "
        "Reality host, Trojan/Shadowsocks hosts without a password, "
        "obviously bad address/port, etc. Use this after "
        "`inspect_user_subscription` spots a suspicious line. "
        "Read-only: only returns a list of issues, does not touch the "
        "host."
    ),
    requires_confirmation=False,
)
async def validate_host(db: Session, host_id: int) -> dict:
    from app.db.models.proxy import InboundHost

    host = (
        db.query(InboundHost).filter(InboundHost.id == host_id).first()
    )
    if not host:
        return {"error": f"Host {host_id} not found"}

    issues = _collect_host_issues(host)
    summary = {
        "error": sum(1 for i in issues if i["level"] == "error"),
        "warning": sum(1 for i in issues if i["level"] == "warning"),
        "info": sum(1 for i in issues if i["level"] == "info"),
    }

    return {
        "host_id": host_id,
        "remark": host.remark,
        "protocol": _host_protocol(host) or None,
        "universal": bool(host.universal),
        "bound_to_inbound": host.inbound is not None,
        "issues": issues,
        "summary": summary,
        "ok": summary["error"] == 0,
    }


# ---------------------------------------------------------------------------
# Bulk host validator
# ---------------------------------------------------------------------------


@register_tool(
    name="scan_hosts_for_issues",
    description=(
        "Bulk-run the same heuristic checks as `validate_host` across "
        "many hosts at once and return only the ones with problems. "
        "Ideal for questions like 'show me every broken host on node X' "
        "or 'which VLESS+Reality hosts are misconfigured'. Filters: "
        "`node_id` (>0 restricts to hosts bound to inbounds on that "
        "node — universal hosts are NOT included when this is set), "
        "`inbound_id` (>0 restricts to one inbound), `protocol` (e.g. "
        "'vless', 'trojan'; case-insensitive). By default returns only "
        "hosts with at least one `error`-level issue; pass "
        "`only_with_errors=False` to also include warnings. Paginated: "
        "`limit` default 100, hard max 500. `total` in the response is "
        "the total number of hosts matching the SQL filter BEFORE the "
        "in-memory error/warning filter — iterate pages with "
        "`next_offset` to be sure you've seen every broken host."
    ),
    requires_confirmation=False,
)
async def scan_hosts_for_issues(
    db: Session,
    node_id: int = 0,
    inbound_id: int = 0,
    protocol: str = "",
    only_with_errors: bool = True,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    from app.db.models import Inbound, InboundHost

    limit = clamp_limit(limit, default=100, maximum=500)
    offset = clamp_offset(offset)

    query = db.query(InboundHost)
    if inbound_id > 0:
        query = query.filter(InboundHost.inbound_id == inbound_id)
    if node_id > 0:
        query = query.join(
            Inbound, InboundHost.inbound_id == Inbound.id
        ).filter(Inbound.node_id == node_id)
    query = query.order_by(InboundHost.id)

    total = query.count()
    hosts = query.offset(offset).limit(limit).all()

    proto_filter = (protocol or "").lower().strip()
    results: list[dict] = []
    ok_count = 0
    for h in hosts:
        host_proto = _host_protocol(h)
        if proto_filter and host_proto != proto_filter:
            continue
        issues = _collect_host_issues(h)
        err_count = sum(1 for i in issues if i["level"] == "error")
        warn_count = sum(1 for i in issues if i["level"] == "warning")
        if err_count == 0 and (only_with_errors or warn_count == 0):
            ok_count += 1
            continue
        results.append({
            "host_id": h.id,
            "remark": h.remark,
            "protocol": host_proto or None,
            "universal": bool(h.universal),
            "inbound_id": h.inbound_id,
            "node_id": h.inbound.node_id if h.inbound else None,
            "errors": err_count,
            "warnings": warn_count,
            "issues": issues,
        })

    return {
        "hosts": results,
        "filter": {
            "node_id": node_id or None,
            "inbound_id": inbound_id or None,
            "protocol": proto_filter or None,
            "only_with_errors": only_with_errors,
        },
        "page_ok_count": ok_count,
        "page_broken_count": len(results),
        **paginated_envelope(total, offset, limit),
    }


# ---------------------------------------------------------------------------
# Reverse credential lookup (UUID / password / subscription URL → username)
# ---------------------------------------------------------------------------


_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _extract_credential(raw: str) -> tuple[str, str] | None:
    """Parse an admin-supplied string into ('uuid'|'password', value).

    Accepts: a bare UUID, a bare password/hex string, or a full
    vless://<uuid>@... / trojan://<pass>@... / vmess://<base64> URL.
    """
    s = (raw or "").strip()
    if not s:
        return None

    low = s.lower()
    for scheme, kind in (("vless://", "uuid"), ("trojan://", "password")):
        if low.startswith(scheme):
            rest = s[len(scheme):]
            at = rest.find("@")
            if at > 0:
                userinfo = unquote(rest[:at]).strip()
                if userinfo and userinfo.lower() != "none":
                    return (kind, userinfo)
            return None  # vless://None@... — nothing to look up

    if low.startswith("vmess://"):
        try:
            b64 = s[len("vmess://"):].split("#", 1)[0].split("?", 1)[0]
            pad = "=" * (-len(b64) % 4)
            decoded = base64.b64decode(b64 + pad).decode(
                "utf-8", errors="replace"
            )
            obj = json.loads(decoded)
            uid = obj.get("id")
            if uid:
                return ("uuid", str(uid))
        except Exception:
            pass
        return None

    if _UUID_RE.match(s):
        return ("uuid", s.lower())
    return ("password", s)


@register_tool(
    name="find_user_by_credential",
    description=(
        "Reverse-lookup a user (or host) by a credential taken from a "
        "subscription. Accepts a UUID (VLESS/VMess), a password "
        "(Trojan/Shadowsocks/Hysteria2), or a full "
        "`vless://<uuid>@...`, `trojan://<pass>@...`, or "
        "`vmess://<base64>` URL — the tool auto-detects the kind and "
        "extracts the credential. It then checks BOTH explicit host-"
        "level credentials (`host.uuid` / `host.password`) AND "
        "per-user derived credentials (`gen_uuid(user.key)` / "
        "`gen_password(user.key)`) so it works regardless of the "
        "panel's AUTH_GENERATION_ALGORITHM setting. Read-only. Use "
        "this when the admin gives you a UUID / password but no "
        "username, or when they paste a single suspicious subscription "
        "line. `max_scan` (default 5000, hard max 50000) caps how many "
        "non-removed users are hashed before giving up — the full user "
        "count and `truncated` flag are returned so you know if you "
        "need to raise it."
    ),
    requires_confirmation=False,
)
async def find_user_by_credential(
    db: Session,
    credential: str,
    max_scan: int = 5000,
) -> dict:
    from app.db.models import InboundHost
    from app.db.models.core import User
    from app.utils.keygen import gen_password, gen_uuid

    parsed = _extract_credential(credential)
    if not parsed:
        return {
            "error": (
                "Could not extract a credential from the input. Pass a "
                "bare UUID, a password, or a full vless://<uuid>@... / "
                "trojan://<pass>@... / vmess://<base64> URL. A "
                "`vless://None@...` link by itself is not enough — "
                "the admin must give a username instead."
            )
        }

    kind, value = parsed
    max_scan = max(1, min(int(max_scan or 5000), 50_000))

    host_matches: list[dict] = []
    if kind == "uuid":
        try:
            norm = str(UUIDType(value))
        except ValueError:
            norm = value.lower()
        rows = (
            db.query(InboundHost)
            .filter(InboundHost.uuid.ilike(norm))
            .limit(25)
            .all()
        )
        for h in rows:
            host_matches.append({
                "host_id": h.id,
                "remark": h.remark,
                "field": "uuid",
                "value": h.uuid,
            })
    else:
        rows = (
            db.query(InboundHost)
            .filter(InboundHost.password == value)
            .limit(25)
            .all()
        )
        for h in rows:
            host_matches.append({
                "host_id": h.id,
                "remark": h.remark,
                "field": "password",
            })

    target_value = value.lower() if kind == "uuid" else value
    user_matches: list[dict] = []
    q = (
        db.query(User.id, User.username, User.key, User.removed)
        .filter(User.removed == False)  # noqa: E712
        .order_by(User.id)
    )
    total_users = q.count()
    rows = q.limit(max_scan).all()

    scanned = 0
    for uid, uname, key, _removed in rows:
        scanned += 1
        if not key:
            continue
        try:
            if kind == "uuid":
                derived = gen_uuid(key).lower()
                if derived == target_value:
                    user_matches.append({
                        "user_id": uid,
                        "username": uname,
                        "match": "derived_uuid",
                    })
            else:
                derived = gen_password(key)
                if derived == target_value:
                    user_matches.append({
                        "user_id": uid,
                        "username": uname,
                        "match": "derived_password",
                    })
        except Exception:
            continue
        if len(user_matches) >= 25:
            break

    truncated = scanned < total_users and not user_matches

    return {
        "input": credential,
        "credential_kind": kind,
        "credential_value": value if kind == "uuid" else "(password redacted)",
        "matches": user_matches,
        "host_matches": host_matches,
        "scanned_users": scanned,
        "total_users": total_users,
        "truncated": truncated,
        "hint": (
            "No match — the credential may belong to a removed user, "
            "to a user past `max_scan`, or it is simply not derived "
            "from any `user.key` in this panel. If `truncated=true`, "
            "retry with a higher `max_scan`."
            if not user_matches and not host_matches
            else None
        ),
    }
