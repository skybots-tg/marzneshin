import logging

from sqlalchemy.orm import Session

from app.ai.tool_registry import register_tool
from app.ai.tools._common import clamp_limit, clamp_offset, paginated_envelope

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
        **paginated_envelope(total, offset, limit),
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
        "Modify an existing host IN PLACE. PREFER THIS over delete_host + create_host "
        "when you need to change any field — deleting and re-creating a host changes "
        "its id, detaches it from services, and breaks any chain that references it. "
        "Only fields whose values differ from the sentinel are updated:\n"
        "- string fields: \"\" preserves the current value; pass the new string to set.\n"
        "- int fields: -1 preserves; 0/positive sets (port/mtu/shadowtls_version/"
        "early_data: 0 effectively clears since the column is nullable).\n"
        "- bool toggles (is_disabled/universal/allowinsecure/mlkem_enabled): pass 1 to "
        "enable, 0 to disable, -1 to preserve.\n"
        "- list fields: [] preserves; a non-empty list replaces the value.\n"
        "- JSON fields are passed as JSON strings (fragment_json, udp_noises_json, "
        "http_headers_json, splithttp_settings_json, mux_settings_json, "
        "reality_short_ids_json).\n"
        "- To explicitly NULL any nullable field, add its name to `clear_fields`, e.g. "
        "clear_fields=[\"sni\", \"reality_public_key\", \"fragment\"]. Allowed names: "
        "sni, host, path, uuid, password, alpn, flow, header_type, dns_servers, "
        "allowed_ips, reality_public_key, reality_short_ids, shadowsocks_method, "
        "mlkem_public_key, mlkem_private_key, fragment, udp_noises, http_headers, "
        "splithttp_settings, mux_settings, host_protocol, host_network, "
        "shadowtls_version, early_data, mtu, port.\n"
        "Enum values: security='inbound_default'|'none'|'tls'; "
        "fingerprint='none'|'chrome'|'firefox'|'safari'|'ios'|'android'|'edge'|'360'|"
        "'qq'|'random'|'randomized'. "
        "Pass service_ids=[1,2] to replace the service list; [] preserves."
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
    protocol: str = "",
    network: str = "",
    fingerprint: str = "",
    alpn: str = "",
    flow: str = "",
    header_type: str = "",
    dns_servers: str = "",
    allowed_ips: str = "",
    reality_public_key: str = "",
    reality_short_ids_json: str = "",
    fragment_json: str = "",
    udp_noises_json: str = "",
    http_headers_json: str = "",
    splithttp_settings_json: str = "",
    mux_settings_json: str = "",
    shadowsocks_method: str = "",
    shadowtls_version: int = -1,
    early_data: int = -1,
    mtu: int = -1,
    mlkem_enabled: int = -1,
    mlkem_public_key: str = "",
    mlkem_private_key: str = "",
    uuid: str = "",
    password: str = "",
    is_disabled: int = -1,
    universal: int = -1,
    allowinsecure: int = -1,
    weight: int = -1,
    service_ids: list = [],
    clear_fields: list = [],
) -> dict:
    import json
    from app.db.models import InboundHost, Service
    from app.models.proxy import InboundHostSecurity

    db_host = db.query(InboundHost).filter(InboundHost.id == host_id).first()
    if not db_host:
        return {"error": f"Host {host_id} not found"}

    _CLEARABLE = {
        "sni", "host", "path", "uuid", "password", "alpn", "flow",
        "header_type", "dns_servers", "allowed_ips", "reality_public_key",
        "reality_short_ids", "shadowsocks_method", "mlkem_public_key",
        "mlkem_private_key", "fragment", "udp_noises", "http_headers",
        "splithttp_settings", "mux_settings", "host_protocol",
        "host_network", "shadowtls_version", "early_data", "mtu", "port",
    }
    clear_set = {f.strip() for f in (clear_fields or []) if f and f.strip()}
    unknown_clear = sorted(clear_set - _CLEARABLE)
    if unknown_clear:
        return {
            "error": (
                f"clear_fields contains unsupported names: {unknown_clear}. "
                f"Allowed: {sorted(_CLEARABLE)}"
            )
        }

    def _set_str(col_attr: str, value: str, target_attr: str | None = None):
        if value:
            setattr(db_host, target_attr or col_attr, value)

    def _parse_json(field_label: str, raw: str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"{field_label}: invalid JSON ({e})")

    try:
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
            try:
                db_host.security = InboundHostSecurity(security)
            except ValueError:
                return {
                    "error": (
                        f"Invalid security '{security}'. "
                        f"Allowed: inbound_default, none, tls."
                    )
                }

        if protocol:
            db_host.host_protocol = protocol
        if network:
            db_host.host_network = network

        if fingerprint:
            allowed_fp = {
                "none", "chrome", "firefox", "safari", "ios", "android",
                "edge", "360", "qq", "random", "randomized",
            }
            if fingerprint not in allowed_fp:
                return {
                    "error": (
                        f"Invalid fingerprint '{fingerprint}'. "
                        f"Allowed: {sorted(allowed_fp)}"
                    )
                }
            db_host.fingerprint = fingerprint

        _set_str("alpn", alpn)
        _set_str("flow", flow)
        _set_str("header_type", header_type)
        _set_str("dns_servers", dns_servers)
        _set_str("allowed_ips", allowed_ips)
        _set_str("reality_public_key", reality_public_key)
        _set_str("shadowsocks_method", shadowsocks_method)
        _set_str("mlkem_public_key", mlkem_public_key)
        _set_str("mlkem_private_key", mlkem_private_key)
        _set_str("uuid", uuid)
        _set_str("password", password)

        if reality_short_ids_json:
            parsed = _parse_json("reality_short_ids_json", reality_short_ids_json)
            if not isinstance(parsed, list):
                return {"error": "reality_short_ids_json must be a JSON list of strings"}
            db_host.reality_short_ids = parsed
        if fragment_json:
            db_host.fragment = _parse_json("fragment_json", fragment_json)
        if udp_noises_json:
            parsed = _parse_json("udp_noises_json", udp_noises_json)
            if not isinstance(parsed, list):
                return {"error": "udp_noises_json must be a JSON list"}
            db_host.udp_noises = parsed
        if http_headers_json:
            parsed = _parse_json("http_headers_json", http_headers_json)
            if not isinstance(parsed, dict):
                return {"error": "http_headers_json must be a JSON object"}
            db_host.http_headers = parsed
        if splithttp_settings_json:
            db_host.splithttp_settings = _parse_json(
                "splithttp_settings_json", splithttp_settings_json
            )
        if mux_settings_json:
            db_host.mux_settings = _parse_json("mux_settings_json", mux_settings_json)

        if shadowtls_version >= 0:
            db_host.shadowtls_version = shadowtls_version or None
        if early_data >= 0:
            db_host.early_data = early_data or None
        if mtu >= 0:
            db_host.mtu = mtu or None

        if weight >= 0:
            db_host.weight = weight
        if is_disabled in (0, 1):
            db_host.is_disabled = bool(is_disabled)
        if universal in (0, 1):
            db_host.universal = bool(universal)
        if allowinsecure in (0, 1):
            db_host.allowinsecure = bool(allowinsecure)
        if mlkem_enabled in (0, 1):
            db_host.mlkem_enabled = bool(mlkem_enabled)

        if service_ids:
            db_host.services = (
                db.query(Service).filter(Service.id.in_(service_ids)).all()
            )

        for f in clear_set:
            setattr(db_host, f, None)
    except ValueError as ve:
        db.rollback()
        return {"error": str(ve)}
    except Exception as ex:
        db.rollback()
        return {"error": f"Failed to modify host: {ex}"}

    db.commit()
    db.refresh(db_host)
    return {
        "success": True,
        "host": _serialize_host_full(db_host),
        "cleared_fields": sorted(clear_set),
    }


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
