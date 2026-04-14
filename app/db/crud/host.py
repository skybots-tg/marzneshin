import json
from typing import List

from sqlalchemy import and_, update, select
from sqlalchemy.orm import Session, joinedload

from app.db.models import (
    Node,
    InboundHost,
    Service,
    Inbound,
    User,
    Backend,
    HostChain,
    users_services,
    inbounds_services,
    hosts_services,
)
from app.models.node import NodeStatus
from app.models.proxy import InboundHost as InboundHostModify
from app.utils.mlkem import ensure_mlkem_keys, MlkemError  # noqa: F401


def add_default_hosts(db: Session, inbounds: List[Inbound]):
    hosts = [
        InboundHost(
            remark="🚀 Marz ({USERNAME}) [{PROTOCOL} - {TRANSPORT}]",
            address="{SERVER_IP}",
            inbound=i,
        )
        for i in inbounds
    ]
    db.add_all(hosts)
    db.commit()


def ensure_node_backends(db: Session, backends, node_id: int):
    old_backends = db.query(Backend).where(Backend.node_id == node_id)
    for backend in old_backends:
        db.delete(backend)
    backends = [
        Backend(
            name=backend.name,
            backend_type=backend.type,
            version=backend.version,
            node_id=node_id,
        )
        for backend in backends
    ]
    db.add_all(backends)
    db.flush()


def ensure_node_inbounds(db: Session, inbounds: List[Inbound], node_id: int):
    current_tags = [
        i[0]
        for i in db.execute(
            select(Inbound.tag).filter(Inbound.node_id == node_id)
        ).all()
    ]
    updated_tags = set(i.tag for i in list(inbounds))
    inbound_additions, tag_deletions = list(), set()
    for tag in current_tags:
        if tag not in updated_tags:
            tag_deletions.add(tag)
    removals = db.query(Inbound).where(
        and_(Inbound.node_id == node_id, Inbound.tag.in_(tag_deletions))
    )
    for i in removals:
        db.delete(i)

    for inb in inbounds:
        if inb.tag in current_tags:
            stmt = (
                update(Inbound)
                .where(
                    and_(Inbound.node_id == node_id, Inbound.tag == inb.tag)
                )
                .values(
                    protocol=json.loads(inb.config)["protocol"],
                    config=inb.config,
                )
            )
            db.execute(stmt)
        else:
            inbound_additions.append(inb)
    new_inbounds = [
        Inbound(
            tag=inb.tag,
            protocol=json.loads(inb.config)["protocol"],
            config=inb.config,
            node_id=node_id,
        )
        for inb in inbound_additions
    ]
    db.add_all(new_inbounds)
    db.flush()
    for i in new_inbounds:
        db.refresh(i)
    add_default_hosts(db, new_inbounds)
    db.commit()


def get_node_users(
    db: Session,
    node_id: int,
):
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        return []

    query = (
        db.query(User.id, User.username, User.key, Inbound, User.device_limit)
        .distinct()
        .join(Inbound.services)
        .join(Service.users)
        .filter(Inbound.node_id == node_id)
        .filter(User.activated == True)
    )

    if node.usage_coefficient > 0:
        query = query.filter(User.data_limit_reached == False)

    return query.all()


def get_user_hosts(db: Session, user_id: int):
    return (
        db.query(InboundHost)
        .distinct()
        .join(User.services)
        .join(Service.inbounds)
        .join(Inbound.hosts)
        .filter(User.id == user_id)
        .all()
    )


def get_inbounds_hosts(
    db: Session, inbound_ids: list[int]
) -> list[InboundHost]:
    return (
        db.query(InboundHost)
        .options(
            joinedload(InboundHost.chain).joinedload(HostChain.chained_host)
        )
        .filter(InboundHost.inbound_id.in_(inbound_ids))
        .filter(InboundHost.is_disabled == False)
        .all()
    )


def get_hosts_for_user(
    session, user_id, service_ids: list[int] | None = None,
    exclude_unhealthy_nodes: bool = False,
):
    """
    Get hosts for a user. Optimized version using JOINs instead of subqueries.

    Args:
        session: Database session
        user_id: User ID
        service_ids: Optional pre-loaded list of service IDs (avoids extra query)
        exclude_unhealthy_nodes: If True, skip hosts belonging to unhealthy nodes
    """
    if service_ids is None:
        service_ids = [
            row[0] for row in session.execute(
                select(users_services.c.service_id).where(
                    users_services.c.user_id == user_id
                )
            ).fetchall()
        ]

    if not service_ids:
        return []

    hosts_with_inbound = (
        session.query(InboundHost)
        .join(Inbound, InboundHost.inbound_id == Inbound.id)
        .join(inbounds_services, Inbound.id == inbounds_services.c.inbound_id)
        .filter(
            InboundHost.is_disabled == False,
            inbounds_services.c.service_id.in_(service_ids)
        )
        .options(
            joinedload(InboundHost.inbound),
            joinedload(InboundHost.chain).joinedload(HostChain.chained_host)
        )
    )

    if exclude_unhealthy_nodes:
        hosts_with_inbound = (
            hosts_with_inbound
            .join(Node, Inbound.node_id == Node.id)
            .filter(Node.status != NodeStatus.unhealthy)
        )

    universal_hosts = (
        session.query(InboundHost)
        .filter(
            InboundHost.is_disabled == False,
            InboundHost.inbound_id.is_(None),
            InboundHost.universal == True
        )
        .options(
            joinedload(InboundHost.chain).joinedload(HostChain.chained_host)
        )
    )

    hosts_direct_service = (
        session.query(InboundHost)
        .join(hosts_services, InboundHost.id == hosts_services.c.host_id)
        .filter(
            InboundHost.is_disabled == False,
            InboundHost.inbound_id.is_(None),
            hosts_services.c.service_id.in_(service_ids)
        )
        .options(
            joinedload(InboundHost.chain).joinedload(HostChain.chained_host)
        )
    )

    all_hosts = hosts_with_inbound.union(universal_hosts).union(hosts_direct_service).all()

    seen_ids = set()
    unique_hosts = []
    for host in all_hosts:
        if host.id not in seen_ids:
            seen_ids.add(host.id)
            unique_hosts.append(host)

    return unique_hosts


def get_node_coefficients(db: Session) -> dict[int, float]:
    """Get mapping of node_id -> usage_coefficient for all nodes."""
    return dict(db.query(Node.id, Node.usage_coefficient).all())


def get_all_inbounds(db: Session):
    return db.query(Inbound).all()


def get_inbound(db: Session, inbound_id: int) -> Inbound | None:
    return db.query(Inbound).filter(Inbound.id == inbound_id).first()


def get_host(db: Session, host_id) -> InboundHost:
    return db.query(InboundHost).filter(InboundHost.id == host_id).first()


def add_host(db: Session, inbound: Inbound | None, host: InboundHostModify):
    mlkem_enabled = getattr(host, "mlkem_enabled", False)
    mlkem_public_key = getattr(host, "mlkem_public_key", None)
    mlkem_private_key = None

    if mlkem_enabled:
        keypair = ensure_mlkem_keys(
            public_key=mlkem_public_key,
            private_key=None,
        )
        mlkem_public_key = keypair.public_key
        mlkem_private_key = keypair.private_key

    host = InboundHost(
        remark=host.remark,
        address=host.address,
        host_network=host.network,
        host_protocol=host.protocol,
        uuid=host.uuid,
        password=host.password,
        port=host.port,
        path=host.path,
        sni=host.sni,
        host=host.host,
        security=host.security,
        alpn=host.alpn.value,
        fingerprint=host.fingerprint,
        fragment=host.fragment.model_dump() if host.fragment else None,
        udp_noises=(
            [noise.model_dump() for noise in host.noise]
            if host.noise
            else None
        ),
        header_type=host.header_type,
        reality_public_key=host.reality_public_key,
        reality_short_ids=host.reality_short_ids,
        mlkem_enabled=mlkem_enabled,
        mlkem_public_key=mlkem_public_key,
        mlkem_private_key=mlkem_private_key,
        flow=host.flow,
        shadowtls_version=host.shadowtls_version,
        shadowsocks_method=host.shadowsocks_method,
        splithttp_settings=(
            host.splithttp_settings.model_dump()
            if host.splithttp_settings
            else None
        ),
        early_data=host.early_data,
        http_headers=host.http_headers,
        mtu=host.mtu,
        dns_servers=host.dns_servers,
        allowed_ips=host.allowed_ips,
        mux_settings=(
            host.mux_settings.model_dump() if host.mux_settings else None
        ),
        allowinsecure=host.allowinsecure,
        weight=host.weight,
        universal=host.universal,
        services=(
            db.query(Service).filter(Service.id.in_(host.service_ids)).all()
        ),
        chain=[
            HostChain(chained_host_id=ch[0])
            for ch in db.query(InboundHost.id)
            .filter(InboundHost.id.in_(host.chain_ids))
            .all()
        ],
    )
    if inbound:
        inbound.hosts.append(host)
    else:
        db.add(host)
    db.commit()
    db.refresh(host)
    return host


def update_host(db: Session, db_host: InboundHost, host: InboundHostModify):
    db_host.remark = host.remark
    db_host.address = host.address
    db_host.uuid = host.uuid
    db_host.password = host.password
    db_host.host_network = host.network
    db_host.host_protocol = host.protocol
    db_host.port = host.port
    db_host.path = host.path
    db_host.sni = host.sni
    db_host.host = host.host
    db_host.security = host.security
    db_host.alpn = host.alpn.value
    db_host.fingerprint = host.fingerprint
    db_host.fragment = host.fragment.model_dump() if host.fragment else None
    db_host.mux_settings = (
        host.mux_settings.model_dump() if host.mux_settings else None
    )
    db_host.is_disabled = host.is_disabled
    db_host.allowinsecure = host.allowinsecure
    db_host.udp_noises = (
        [noise.model_dump() for noise in host.noise] if host.noise else None
    )
    db_host.header_type = host.header_type
    db_host.reality_public_key = host.reality_public_key
    db_host.reality_short_ids = host.reality_short_ids
    mlkem_enabled = getattr(host, "mlkem_enabled", False)
    db_host.mlkem_enabled = mlkem_enabled

    if mlkem_enabled:
        current_public = (
            getattr(host, "mlkem_public_key", None) or db_host.mlkem_public_key
        )
        current_private = db_host.mlkem_private_key

        keypair = ensure_mlkem_keys(
            public_key=current_public,
            private_key=current_private,
        )
        db_host.mlkem_public_key = keypair.public_key
        db_host.mlkem_private_key = keypair.private_key
    else:
        db_host.mlkem_public_key = getattr(host, "mlkem_public_key", None)
        db_host.mlkem_private_key = None
    db_host.flow = host.flow
    db_host.shadowtls_version = host.shadowtls_version
    db_host.shadowsocks_method = host.shadowsocks_method
    db_host.splithttp_settings = (
        host.splithttp_settings.model_dump()
        if host.splithttp_settings
        else None
    )
    db_host.early_data = host.early_data

    chain_ids = [
        int(i[0])
        for i in db.query(InboundHost.id)
        .filter(InboundHost.id.in_(host.chain_ids))
        .all()
    ]
    chain_nodes = [
        HostChain(host_id=db_host.id, chained_host_id=chain_id)
        for chain_id in chain_ids
    ]
    db_host.chain = chain_nodes
    db_host.http_headers = host.http_headers
    db_host.mtu = host.mtu
    db_host.dns_servers = host.dns_servers
    db_host.allowed_ips = host.allowed_ips
    db_host.universal = host.universal
    db_host.services = (
        db.query(Service).filter(Service.id.in_(host.service_ids)).all()
    )
    db_host.weight = host.weight
    db.commit()
    db.refresh(db_host)
    return db_host
