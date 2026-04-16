import logging

from sqlalchemy.orm import Session

from app.ai.tool_registry import register_tool
from app.ai.tools._common import clamp_limit, clamp_offset

logger = logging.getLogger(__name__)


@register_tool(
    name="list_hosts",
    description=(
        "List hosts (proxy endpoints) with pagination. "
        "ALWAYS provide a filter such as `remark` or `inbound_id` when looking for "
        "specific entries — the table can contain thousands of rows. "
        "Default limit is 20; hard maximum is 100. "
        "Returns remark, address, port, protocol, security, inbound info, "
        "associated services, and disabled status."
    ),
    requires_confirmation=False,
)
async def list_hosts(
    db: Session,
    limit: int = 20,
    offset: int = 0,
    remark: str = "",
    inbound_id: int = 0,
    universal_only: bool = False,
) -> dict:
    from app.db.models import InboundHost

    limit = clamp_limit(limit)
    offset = clamp_offset(offset)

    query = db.query(InboundHost)
    if remark:
        query = query.filter(InboundHost.remark.ilike(f"%{remark}%"))
    if inbound_id > 0:
        query = query.filter(InboundHost.inbound_id == inbound_id)
    if universal_only:
        query = query.filter(InboundHost.universal == True, InboundHost.inbound_id.is_(None))  # noqa: E712
    query = query.order_by(InboundHost.weight.desc(), InboundHost.id.desc())
    total = query.count()
    hosts = query.offset(offset).limit(limit).all()

    return {
        "hosts": [_serialize_host_short(h) for h in hosts],
        "total": total,
        "offset": offset,
        "limit": limit,
        "truncated": total > offset + limit,
    }


@register_tool(
    name="get_host_info",
    description=(
        "Get detailed information about a specific host by its ID. "
        "Returns all fields including security settings, TLS, fingerprint, "
        "fragment, reality keys, chain, associated services, and inbound."
    ),
    requires_confirmation=False,
)
async def get_host_info(db: Session, host_id: int) -> dict:
    from app.db.crud import get_host

    host = get_host(db, host_id)
    if not host:
        return {"error": f"Host {host_id} not found"}
    return _serialize_host_full(host)


@register_tool(
    name="create_host",
    description=(
        "Create a new host (proxy endpoint). "
        "Pass inbound_id > 0 to bind the host to a specific inbound (host is then "
        "visible only to services that include that inbound). "
        "Pass inbound_id = 0 to create a UNIVERSAL host — it becomes visible to ALL "
        "services at once, which is what 'universal for all users' means. "
        "For universal hosts, service_ids is ignored. "
        "`security` values: 'inbound_default', 'none', 'tls'. "
        "`protocol` values: 'vless', 'vmess', 'trojan', 'shadowsocks', "
        "'shadowsocks2022', 'hysteria2', 'wireguard', 'tuic', 'shadowtls' "
        "(leave empty to inherit from the inbound)."
    ),
    requires_confirmation=True,
)
async def create_host(
    db: Session,
    remark: str,
    address: str,
    inbound_id: int = 0,
    port: int = 0,
    sni: str = "",
    host: str = "",
    path: str = "",
    security: str = "inbound_default",
    protocol: str = "",
    network: str = "",
    fingerprint: str = "",
    alpn: str = "",
    allowinsecure: bool = False,
    is_disabled: bool = False,
    weight: int = 1,
    service_ids: list = [],
) -> dict:
    from app.db import crud
    from app.models.proxy import (
        InboundHost as InboundHostModel,
        InboundHostSecurity,
    )

    if not remark.strip():
        return {"error": "Remark must not be empty"}
    if not address.strip():
        return {"error": "Address must not be empty"}

    inbound = None
    universal = False
    if inbound_id > 0:
        inbound = crud.get_inbound(db, inbound_id)
        if not inbound:
            return {"error": f"Inbound {inbound_id} not found"}
    else:
        universal = True

    try:
        sec = InboundHostSecurity(security) if security else InboundHostSecurity.inbound_default
    except ValueError:
        return {
            "error": (
                f"Invalid security '{security}'. "
                f"Allowed: inbound_default, none, tls."
            )
        }

    payload: dict = {
        "remark": remark.strip(),
        "address": address.strip(),
        "port": port if port > 0 else None,
        "sni": sni or None,
        "host": host or None,
        "path": path or None,
        "security": sec,
        "allowinsecure": allowinsecure,
        "is_disabled": is_disabled,
        "weight": weight,
        "universal": universal,
        "service_ids": [] if universal else list(service_ids or []),
    }
    if protocol:
        payload["protocol"] = protocol
    if network:
        payload["network"] = network
    if fingerprint:
        payload["fingerprint"] = fingerprint
    if alpn:
        payload["alpn"] = alpn

    try:
        host_model = InboundHostModel(**payload)
    except Exception as e:
        return {"error": f"Validation error: {str(e)}"}

    try:
        db_host = crud.add_host(db, inbound, host_model)
    except Exception as e:
        return {"error": f"Failed to create host: {str(e)}"}

    return {"success": True, "host": _serialize_host_short(db_host)}


@register_tool(
    name="modify_host",
    description=(
        "Modify a host's settings. Only fields whose values differ from the sentinel "
        "are updated (empty strings and negative numbers are ignored). "
        "To change toggles like is_disabled / universal / allowinsecure, pass 1 to "
        "enable, 0 to disable, or leave at -1 to preserve the current value. "
        "Pass service_ids to reassign the host to different services."
    ),
    requires_confirmation=True,
)
async def modify_host(
    db: Session,
    host_id: int,
    remark: str = "",
    address: str = "",
    port: int = -1,
    sni: str = "",
    host: str = "",
    path: str = "",
    security: str = "",
    is_disabled: int = -1,
    universal: int = -1,
    allowinsecure: int = -1,
    weight: int = -1,
    service_ids: list = [],
) -> dict:
    from app.db.models import InboundHost, Service

    db_host = db.query(InboundHost).filter(InboundHost.id == host_id).first()
    if not db_host:
        return {"error": f"Host {host_id} not found"}

    if remark:
        db_host.remark = remark
    if address:
        db_host.address = address
    if port >= 0:
        db_host.port = port or None
    if sni:
        db_host.sni = sni
    if host:
        db_host.host = host
    if path:
        db_host.path = path
    if security:
        db_host.security = security
    if weight >= 0:
        db_host.weight = weight
    if is_disabled in (0, 1):
        db_host.is_disabled = bool(is_disabled)
    if universal in (0, 1):
        db_host.universal = bool(universal)
    if allowinsecure in (0, 1):
        db_host.allowinsecure = bool(allowinsecure)
    if service_ids:
        db_host.services = (
            db.query(Service).filter(Service.id.in_(service_ids)).all()
        )

    db.commit()
    db.refresh(db_host)
    return {"success": True, "host": _serialize_host_short(db_host)}


@register_tool(
    name="delete_host",
    description=(
        "DANGEROUS: permanently delete a host by its ID. "
        "All users depending on this host through a service will lose it immediately. "
        "Confirm with the operator which host_id is meant before calling."
    ),
    requires_confirmation=True,
)
async def delete_host(db: Session, host_id: int) -> dict:
    from app.db.crud import get_host

    db_host = get_host(db, host_id)
    if not db_host:
        return {"error": f"Host {host_id} not found"}

    remark = db_host.remark
    try:
        db.delete(db_host)
        db.commit()
    except Exception as e:
        db.rollback()
        return {"error": f"Failed to delete host: {str(e)}"}

    return {"success": True, "message": f"Host '{remark}' (id={host_id}) deleted"}


@register_tool(
    name="bulk_toggle_hosts",
    description=(
        "Enable or disable a set of hosts by explicit id list. "
        "Accepts host_ids (e.g. [1, 5, 12]) and a boolean `disabled`. "
        "Does NOT accept filters — callers must select the ids deliberately (use "
        "list_hosts first). Operates in a single transaction."
    ),
    requires_confirmation=True,
)
async def bulk_toggle_hosts(db: Session, host_ids: list = [], disabled: bool = False) -> dict:
    from app.db.models import InboundHost

    if not host_ids:
        return {"error": "host_ids must be a non-empty list of integers"}

    try:
        ids = [int(h) for h in host_ids]
    except (TypeError, ValueError):
        return {"error": "host_ids must contain integers only"}

    rows = db.query(InboundHost).filter(InboundHost.id.in_(ids)).all()
    found_ids = {r.id for r in rows}
    missing = [i for i in ids if i not in found_ids]

    for r in rows:
        r.is_disabled = bool(disabled)
    db.commit()

    return {
        "success": True,
        "updated": list(found_ids),
        "missing": missing,
        "disabled": bool(disabled),
    }


@register_tool(
    name="get_service_hosts",
    description=(
        "Get all hosts associated with a specific service (by service ID). "
        "This shows what proxy endpoints users of this service can connect to. "
        "Relationship: User → Service → (Inbounds → Hosts) + (direct Hosts via hosts_services)."
    ),
    requires_confirmation=False,
)
async def get_service_hosts(db: Session, service_id: int) -> dict:
    from app.db.models import InboundHost, Inbound, Service
    from app.db.models.associations import inbounds_services, hosts_services

    service = db.query(Service).filter(Service.id == service_id).first()
    if not service:
        return {"error": f"Service {service_id} not found"}

    via_inbound = (
        db.query(InboundHost)
        .join(Inbound, InboundHost.inbound_id == Inbound.id)
        .join(inbounds_services, Inbound.id == inbounds_services.c.inbound_id)
        .filter(inbounds_services.c.service_id == service_id)
        .all()
    )

    direct = (
        db.query(InboundHost)
        .join(hosts_services, InboundHost.id == hosts_services.c.host_id)
        .filter(hosts_services.c.service_id == service_id)
        .all()
    )

    universal = (
        db.query(InboundHost)
        .filter(InboundHost.universal == True, InboundHost.inbound_id.is_(None))  # noqa: E712
        .all()
    )

    seen = set()
    all_hosts = []
    for h in via_inbound + direct + universal:
        if h.id not in seen:
            seen.add(h.id)
            all_hosts.append(h)

    return {
        "service": {"id": service.id, "name": service.name},
        "hosts": [_serialize_host_short(h) for h in all_hosts],
        "total": len(all_hosts),
    }


def _serialize_host_short(h) -> dict:
    return {
        "id": h.id,
        "remark": h.remark,
        "address": h.address,
        "port": h.port,
        "protocol": str(h.protocol) if h.protocol else None,
        "network": h.network,
        "security": str(h.security) if h.security else None,
        "sni": h.sni,
        "is_disabled": h.is_disabled,
        "weight": h.weight,
        "universal": h.universal,
        "inbound": (
            {
                "id": h.inbound.id,
                "tag": h.inbound.tag,
                "protocol": str(h.inbound.protocol),
                "node_id": h.inbound.node_id,
            }
            if h.inbound
            else None
        ),
        "service_ids": h.service_ids,
    }


def _serialize_host_full(h) -> dict:
    base = _serialize_host_short(h)
    base.update({
        "host_header": h.host,
        "path": h.path,
        "fingerprint": str(h.fingerprint) if h.fingerprint else None,
        "alpn": str(h.alpn) if h.alpn else None,
        "allowinsecure": h.allowinsecure,
        "fragment": h.fragment,
        "header_type": h.header_type,
        "reality_public_key": h.reality_public_key,
        "reality_short_ids": h.reality_short_ids,
        "flow": h.flow,
        "mlkem_enabled": h.mlkem_enabled,
        "shadowtls_version": h.shadowtls_version,
        "shadowsocks_method": h.shadowsocks_method,
        "mtu": h.mtu,
        "dns_servers": h.dns_servers,
        "allowed_ips": h.allowed_ips,
        "early_data": h.early_data,
        "http_headers": h.http_headers,
        "udp_noises": h.udp_noises,
        "chain_ids": h.chain_ids,
        "services": [
            {"id": s.id, "name": s.name} for s in h.services
        ] if h.services else [],
    })
    return base
