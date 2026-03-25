from sqlalchemy import Column, ForeignKey, Integer, Table

from app.db.base import Base

admins_services = Table(
    "admins_services",
    Base.metadata,
    Column("admin_id", ForeignKey("admins.id"), primary_key=True),
    Column("service_id", ForeignKey("services.id"), primary_key=True),
)

inbounds_services = Table(
    "inbounds_services",
    Base.metadata,
    Column("inbound_id", ForeignKey("inbounds.id"), primary_key=True),
    Column("service_id", ForeignKey("services.id"), primary_key=True),
)

users_services = Table(
    "users_services",
    Base.metadata,
    Column("user_id", ForeignKey("users.id"), primary_key=True),
    Column("service_id", ForeignKey("services.id"), primary_key=True),
)

hosts_services = Table(
    "hosts_services",
    Base.metadata,
    Column("host_id", ForeignKey("hosts.id"), primary_key=True),
    Column("service_id", ForeignKey("services.id"), primary_key=True),
)
