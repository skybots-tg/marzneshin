from datetime import datetime

import sqlalchemy.sql
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.db.base import Base


class UserDevice(Base):
    """Logical device for a user identified by fingerprint"""
    __tablename__ = "user_devices"
    __table_args__ = (
        UniqueConstraint("user_id", "fingerprint", "fingerprint_version"),
    )

    id = Column(BigInteger, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    # Device identification
    fingerprint = Column(String(128), nullable=False)
    fingerprint_version = Column(Integer, nullable=False, default=1, server_default="1")

    # Human-readable info
    display_name = Column(String(64))
    client_name = Column(String(64))
    client_type = Column(String(32), nullable=False, default="other", server_default="other")

    # Timestamps
    first_seen_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_seen_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Last known state
    last_node_id = Column(Integer, ForeignKey("nodes.id", ondelete="SET NULL"))
    last_ip_id = Column(BigInteger)  # FK to UserDeviceIP, added after table creation

    # Security
    is_blocked = Column(Boolean, nullable=False, default=False, server_default=sqlalchemy.sql.false())
    trust_level = Column(Integer, nullable=False, default=0, server_default="0")

    # Metadata
    meta = Column(JSON, nullable=False, default=dict, server_default='{}')

    # Relationships
    user = relationship("User", backref="devices")
    last_node = relationship("Node", foreign_keys=[last_node_id])
    ips = relationship("UserDeviceIP", back_populates="device", cascade="all, delete-orphan")
    traffic_records = relationship("UserDeviceTraffic", back_populates="device", cascade="all, delete-orphan")


class UserDeviceIP(Base):
    """IP addresses used by a device"""
    __tablename__ = "user_device_ips"
    __table_args__ = (
        UniqueConstraint("device_id", "ip"),
    )

    id = Column(BigInteger, primary_key=True)
    device_id = Column(BigInteger, ForeignKey("user_devices.id", ondelete="CASCADE"), nullable=False, index=True)
    ip = Column(String(45), nullable=False, index=True)  # VARCHAR to support both IPv4/IPv6

    # Timestamps
    first_seen_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_seen_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)

    # Statistics
    connect_count = Column(BigInteger, nullable=False, default=0, server_default="0")
    upload_bytes = Column(BigInteger, nullable=False, default=0, server_default="0")
    download_bytes = Column(BigInteger, nullable=False, default=0, server_default="0")

    # Geo/ASN enrichment
    asn = Column(Integer)
    asn_org = Column(String(128))
    country_code = Column(String(2), index=True)
    region = Column(String(64))
    city = Column(String(64))
    is_datacenter = Column(Boolean)

    # Metadata
    meta = Column(JSON, nullable=False, default=dict, server_default='{}')

    # Relationships
    device = relationship("UserDevice", back_populates="ips")


class UserDeviceTraffic(Base):
    """Aggregated traffic data by device, node and time bucket (5 min)"""
    __tablename__ = "user_device_traffic"
    __table_args__ = (
        UniqueConstraint("device_id", "node_id", "bucket_start"),
    )

    id = Column(BigInteger, primary_key=True)
    device_id = Column(BigInteger, ForeignKey("user_devices.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    node_id = Column(Integer, ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False, index=True)

    bucket_start = Column(DateTime, nullable=False, index=True)
    bucket_seconds = Column(Integer, nullable=False, default=300, server_default="300")

    upload_bytes = Column(BigInteger, nullable=False, default=0, server_default="0")
    download_bytes = Column(BigInteger, nullable=False, default=0, server_default="0")
    connect_count = Column(BigInteger, nullable=False, default=0, server_default="0")

    meta = Column(JSON, nullable=False, default=dict, server_default='{}')

    device = relationship("UserDevice", back_populates="traffic_records")
    user = relationship("User")
    node = relationship("Node")


class UserDeviceTrafficDaily(Base):
    """Daily aggregate of device traffic (from 5-min buckets older than 7 days)"""
    __tablename__ = "user_device_traffic_daily"
    __table_args__ = (
        UniqueConstraint("device_id", "node_id", "date"),
        Index("ix_devtraffic_daily_user", "user_id", "date"),
        Index("ix_devtraffic_daily_device", "device_id", "date"),
    )

    id = Column(BigInteger, primary_key=True)
    device_id = Column(BigInteger, ForeignKey("user_devices.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    node_id = Column(Integer, ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False)
    date = Column(Date, nullable=False, index=True)

    upload_bytes = Column(BigInteger, nullable=False, default=0, server_default="0")
    download_bytes = Column(BigInteger, nullable=False, default=0, server_default="0")
    connect_count = Column(BigInteger, nullable=False, default=0, server_default="0")


class UserDeviceTrafficWeekly(Base):
    """Weekly aggregate of device traffic (from daily rows older than 90 days)"""
    __tablename__ = "user_device_traffic_weekly"
    __table_args__ = (
        UniqueConstraint("device_id", "node_id", "week_start"),
        Index("ix_devtraffic_weekly_user", "user_id", "week_start"),
        Index("ix_devtraffic_weekly_device", "device_id", "week_start"),
    )

    id = Column(BigInteger, primary_key=True)
    device_id = Column(BigInteger, ForeignKey("user_devices.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    node_id = Column(Integer, ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False)
    week_start = Column(Date, nullable=False, index=True)

    upload_bytes = Column(BigInteger, nullable=False, default=0, server_default="0")
    download_bytes = Column(BigInteger, nullable=False, default=0, server_default="0")
    connect_count = Column(BigInteger, nullable=False, default=0, server_default="0")
