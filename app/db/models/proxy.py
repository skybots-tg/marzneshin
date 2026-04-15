from datetime import datetime

import sqlalchemy.sql
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.ext.orderinglist import ordering_list
from sqlalchemy.orm import relationship
from sqlalchemy.sql.expression import text

from app.db.base import Base
from app.models.node import NodeStatus
from app.models.proxy import (
    InboundHostFingerprint,
    InboundHostSecurity,
    ProxyTypes,
)
from .associations import inbounds_services, hosts_services


class Backend(Base):
    __tablename__ = "backends"

    id = Column(Integer, primary_key=True)
    name = Column(String(64), nullable=False)
    node_id = Column(Integer, ForeignKey("nodes.id"), index=True)
    node = relationship("Node", back_populates="backends")
    backend_type = Column(String(32), nullable=False)
    version = Column(String(32))
    running = Column(Boolean, default=True, nullable=False)


class Inbound(Base):
    __tablename__ = "inbounds"
    __table_args__ = (UniqueConstraint("node_id", "tag"),)

    id = Column(Integer, primary_key=True)
    protocol = Column(Enum(ProxyTypes))
    tag = Column(String(256), nullable=False)
    config = Column(String(512), nullable=False)
    node_id = Column(Integer, ForeignKey("nodes.id"), index=True)
    node = relationship("Node", back_populates="inbounds")
    services = relationship(
        "Service", secondary=inbounds_services, back_populates="inbounds"
    )
    hosts = relationship(
        "InboundHost",
        back_populates="inbound",
        cascade="all, delete, delete-orphan",
    )

    @property
    def service_ids(self):
        return [service.id for service in self.services]


class HostChain(Base):
    __tablename__ = "host_chains"

    host_id = Column(Integer, ForeignKey("hosts.id"), primary_key=True)
    chained_host_id = Column(Integer, ForeignKey("hosts.id"))
    seq = Column(Integer, primary_key=True)

    host = relationship(
        "InboundHost", foreign_keys=[host_id], back_populates="chain"
    )
    chained_host = relationship(
        "InboundHost",
        foreign_keys=[chained_host_id],
        lazy="joined",
    )


class InboundHost(Base):
    __tablename__ = "hosts"

    id = Column(Integer, primary_key=True)
    remark = Column(String(256), nullable=False)
    address = Column(String(256), nullable=False)
    host_protocol = Column(String(32))
    host_network = Column(String(32))
    uuid = Column(String(36))
    password = Column(String(128))
    port = Column(Integer)
    path = Column(String(256))
    sni = Column(String(1024))
    host = Column(String(1024))
    security = Column(
        Enum(InboundHostSecurity),
        nullable=False,
        default=InboundHostSecurity.inbound_default,
    )
    alpn = Column(
        String(32),
        server_default=sqlalchemy.sql.null(),
    )
    fingerprint = Column(
        Enum(InboundHostFingerprint),
        nullable=False,
        default=InboundHostSecurity.none,
        server_default=InboundHostSecurity.none.name,
    )

    fragment = Column(JSON())
    udp_noises = Column(JSON())
    http_headers = Column(JSON())
    dns_servers = Column(String(128))
    mtu = Column(Integer)
    allowed_ips = Column(Text())
    header_type = Column(String(32))
    reality_public_key = Column(String(128))
    reality_short_ids = Column(JSON())
    flow = Column(String(32))
    shadowtls_version = Column(Integer)
    shadowsocks_method = Column(String(32))
    splithttp_settings = Column(JSON())
    mux_settings = Column(JSON())
    early_data = Column(Integer)
    # ML-KEM настройки для VLESS/Reality и других протоколов.
    # public/private: строки в формате, который возвращает Xray (обычно base64/hex).
    mlkem_enabled = Column(
        Boolean,
        default=False,
        nullable=False,
        server_default=sqlalchemy.sql.false(),
    )
    mlkem_public_key = Column(String(512))
    mlkem_private_key = Column(String(4096))
    inbound_id = Column(Integer, ForeignKey("inbounds.id"), nullable=True)
    inbound = relationship("Inbound", back_populates="hosts", lazy="joined")
    allowinsecure = Column(Boolean, default=False)
    is_disabled = Column(Boolean, default=False)
    weight = Column(Integer, default=1, nullable=False, server_default="1")

    universal = Column(
        Boolean,
        default=False,
        nullable=False,
        server_default=sqlalchemy.sql.false(),
    )
    services = relationship("Service", secondary=hosts_services)

    @property
    def service_ids(self):
        return [service.id for service in self.services]

    chain = relationship(
        "HostChain",
        foreign_keys="[HostChain.host_id]",
        order_by=HostChain.seq,
        collection_class=ordering_list("seq"),
        lazy="joined",
        cascade="all, delete-orphan",
    )

    @property
    def chain_ids(self):
        return [c.chained_host_id for c in self.chain]

    @property
    def protocol(self):
        return self.inbound.protocol if self.inbound else self.host_protocol

    @property
    def network(self):
        return self.host_network

    @property
    def noise(self):
        return self.udp_noises


class Node(Base):
    __tablename__ = "nodes"
    __table_args__ = (UniqueConstraint("address", "port"),)
    id = Column(Integer, primary_key=True)
    name = Column(String(256), unique=True)
    connection_backend = Column(String(32))
    address = Column(String(256))
    port = Column(Integer)
    xray_version = Column(String(32))
    inbounds = relationship(
        "Inbound", back_populates="node", cascade="all, delete"
    )
    backends = relationship(
        "Backend", back_populates="node", cascade="all, delete"
    )
    status = Column(
        Enum(NodeStatus), nullable=False, default=NodeStatus.unhealthy
    )
    last_status_change = Column(DateTime, default=datetime.utcnow)
    message = Column(String(1024))
    created_at = Column(DateTime, default=datetime.utcnow)
    uplink = Column(BigInteger, default=0)
    downlink = Column(BigInteger, default=0)
    user_usages = relationship(
        "NodeUserUsage",
        back_populates="node",
        cascade="save-update, merge",
    )
    usages = relationship(
        "NodeUsage",
        back_populates="node",
        cascade="save-update, merge",
    )
    usage_coefficient = Column(
        Float, nullable=False, server_default=text("1.0"), default=1
    )

    @property
    def inbound_ids(self):
        return [inbound.id for inbound in self.inbounds]

    @property
    def adblock_enabled(self) -> bool:
        cfg = getattr(self, "filtering_config", None)
        return cfg.adblock_enabled if cfg else False


class NodeUserUsage(Base):
    __tablename__ = "node_user_usages"
    __table_args__ = (UniqueConstraint("created_at", "user_id", "node_id"),)

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, nullable=False)  # one hour per record
    user_id = Column(Integer, ForeignKey("users.id"))
    user = relationship("User", back_populates="node_usages")
    node_id = Column(Integer, ForeignKey("nodes.id"))
    node = relationship("Node", back_populates="user_usages")
    used_traffic = Column(BigInteger, default=0)


class NodeUserUsageDaily(Base):
    """Aggregated daily traffic per user per node (compressed from hourly records)."""
    __tablename__ = "node_user_usages_daily"
    __table_args__ = (UniqueConstraint("date", "user_id", "node_id"),)

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    node_id = Column(Integer, ForeignKey("nodes.id"), index=True)
    used_traffic = Column(BigInteger, default=0)


class NodeUsage(Base):
    __tablename__ = "node_usages"
    __table_args__ = (UniqueConstraint("created_at", "node_id"),)

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, nullable=False)  # one hour per record
    node_id = Column(Integer, ForeignKey("nodes.id"))
    node = relationship("Node", back_populates="usages")
    uplink = Column(BigInteger, default=0)
    downlink = Column(BigInteger, default=0)


class NodeUsageDaily(Base):
    """Aggregated daily traffic per node (compressed from hourly records)."""
    __tablename__ = "node_usages_daily"
    __table_args__ = (UniqueConstraint("date", "node_id"),)

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False, index=True)
    node_id = Column(Integer, ForeignKey("nodes.id"), index=True)
    uplink = Column(BigInteger, default=0)
    downlink = Column(BigInteger, default=0)
