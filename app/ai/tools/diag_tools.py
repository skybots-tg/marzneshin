import asyncio
import logging

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

    issues: list[dict] = []

    def add(level: str, field: str | None, message: str) -> None:
        issues.append({"level": level, "field": field, "message": message})

    protocol = (
        host.inbound.protocol.value
        if host.inbound
        else (host.host_protocol or "")
    )
    protocol = (protocol or "").lower()

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

    summary = {
        "error": sum(1 for i in issues if i["level"] == "error"),
        "warning": sum(1 for i in issues if i["level"] == "warning"),
        "info": sum(1 for i in issues if i["level"] == "info"),
    }

    return {
        "host_id": host_id,
        "remark": host.remark,
        "protocol": protocol or None,
        "universal": bool(host.universal),
        "bound_to_inbound": host.inbound is not None,
        "issues": issues,
        "summary": summary,
        "ok": summary["error"] == 0,
    }
