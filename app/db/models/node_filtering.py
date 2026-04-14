from sqlalchemy import (
    Boolean,
    Column,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql.expression import text

from app.db.base import Base
from app.models.node_filtering import DnsProvider


class NodeFilteringConfig(Base):
    __tablename__ = "node_filtering_config"

    id = Column(Integer, primary_key=True)
    node_id = Column(
        Integer, ForeignKey("nodes.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    node = relationship("Node", backref="filtering_config", uselist=False)

    adblock_enabled = Column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    dns_provider = Column(
        Enum(DnsProvider),
        nullable=False,
        default=DnsProvider.adguard_dns_public,
    )
    dns_address = Column(String(512), nullable=True)
    adguard_home_port = Column(
        Integer, nullable=False, default=5353, server_default=text("5353")
    )
    adguard_home_installed = Column(
        Boolean, nullable=False, default=False, server_default="0"
    )


class NodeSSHCredentials(Base):
    __tablename__ = "node_ssh_credentials"

    id = Column(Integer, primary_key=True)
    node_id = Column(
        Integer, ForeignKey("nodes.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    node = relationship("Node", backref="ssh_credentials", uselist=False)

    encrypted_data = Column(Text, nullable=False)
    encryption_salt = Column(String(128), nullable=False)
    pin_hash = Column(String(256), nullable=False)
