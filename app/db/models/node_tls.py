from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import relationship

from app.db.base import Base


class NodeTLSProvisioning(Base):
    """One row per node that has been provisioned with Caddy + TLS + landing.

    Stores enough state to (a) render UI without re-querying the node,
    (b) detect when a renew is overdue, (c) tell the AI which template
    is currently live so it can rotate it on demand. The actual cert
    bytes live on the node's filesystem (Caddy storage); we never copy
    them back to the panel.
    """
    __tablename__ = "node_tls_provisioning"

    id = Column(Integer, primary_key=True)
    node_id = Column(
        Integer,
        ForeignKey("nodes.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    node = relationship("Node", backref="tls_provisioning", uselist=False)

    domain = Column(String(253), nullable=False)
    landing_template = Column(String(64), nullable=False)
    grpc_service_name = Column(String(64), nullable=False)
    uds_path = Column(String(255), nullable=False)
    contact_email = Column(String(254), nullable=False)
    cert_issued_at = Column(DateTime, nullable=True)
    cert_expires_at = Column(DateTime, nullable=True)
    last_renew_attempt_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
