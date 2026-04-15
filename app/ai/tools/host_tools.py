import logging

from sqlalchemy.orm import Session

from app.ai.tool_registry import register_tool

logger = logging.getLogger(__name__)


@register_tool(
    name="list_hosts",
    description=(
        "List all hosts (proxy endpoints) with pagination. "
        "Returns remark, address, port, protocol, security, inbound info, "
        "associated services, and disabled status. "
        "Hosts are what users connect to — they belong to services via inbounds or directly."
    ),
    requires_confirmation=False,
)
async def list_hosts(
    db: Session, limit: int = 50, offset: int = 0, remark: str = ""
) -> dict:
    from app.db.models import InboundHost

    query = db.query(InboundHost)
    if remark:
        query = query.filter(InboundHost.remark.ilike(f"%{remark}%"))
    query = query.order_by(InboundHost.weight.desc(), InboundHost.id.desc())
    total = query.count()
    hosts = query.offset(offset).limit(limit).all()

    return {
        "hosts": [_serialize_host_short(h) for h in hosts],
        "total": total,
        "offset": offset,
        "limit": limit,
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
    name="modify_host",
    description=(
        "Modify a host's settings. Only provided (non-empty) fields will be updated. "
        "Common use cases: change address/port, toggle disabled, update SNI/host header, "
        "change remark, update security settings. "
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
    is_disabled: bool = False,
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
        db_host.port = port
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
    db_host.is_disabled = is_disabled
    if service_ids:
        db_host.services = (
            db.query(Service).filter(Service.id.in_(service_ids)).all()
        )

    db.commit()
    db.refresh(db_host)
    return {"success": True, "host": _serialize_host_short(db_host)}


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
        .filter(InboundHost.universal == True, InboundHost.inbound_id.is_(None))
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
