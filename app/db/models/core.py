import secrets
from datetime import datetime

import sqlalchemy.sql
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    and_,
    func,
    select,
)
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship, column_property

from app.config.env import SUBSCRIPTION_URL_PREFIX
from app.db.base import Base
from app.models.user import (
    UserDataUsageResetStrategy,
    UserStatus,
    UserExpireStrategy,
)
from .associations import admins_services, users_services, inbounds_services


class Admin(Base):
    __tablename__ = "admins"

    id = Column(Integer, primary_key=True)
    username = Column(String(32), unique=True, index=True)
    hashed_password = Column(String(128))
    users = relationship("User", back_populates="admin")
    services = relationship(
        "Service",
        secondary=admins_services,
        back_populates="admins",
        lazy="joined",
    )
    enabled = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default=sqlalchemy.sql.true(),
    )
    all_services_access = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default=sqlalchemy.sql.false(),
    )
    modify_users_access = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default=sqlalchemy.sql.true(),
    )
    created_at = Column(DateTime, default=datetime.utcnow)
    is_sudo = Column(Boolean, default=False)
    password_reset_at = Column(DateTime)
    subscription_url_prefix = Column(
        String(256),
        nullable=False,
        default="",
        server_default=sqlalchemy.sql.text(""),
    )

    @property
    def service_ids(self):
        return [service.id for service in self.services]

    @classmethod
    def __declare_last__(cls):
        cls.users_data_usage = column_property(
            select(func.coalesce(func.sum(User.lifetime_used_traffic), 0))
            .where(User.admin_id == cls.id)
            .correlate_except(User)
            .scalar_subquery()
        )


class Service(Base):
    __tablename__ = "services"
    id = Column(Integer, primary_key=True)
    name = Column(String(64))
    admins = relationship(
        "Admin", secondary=admins_services, back_populates="services"
    )
    users = relationship(
        "User", secondary=users_services, back_populates="services"
    )
    inbounds = relationship(
        "Inbound", secondary=inbounds_services, back_populates="services"
    )

    @property
    def inbound_ids(self):
        return [inbound.id for inbound in self.inbounds]

    @property
    def user_ids(self):
        from sqlalchemy.orm.attributes import instance_state
        if "users" not in instance_state(self).dict:
            return []
        return [user.id for user in self.users if not user.removed]

    @classmethod
    def __declare_last__(cls):
        cls.user_count = column_property(
            select(func.count(users_services.c.user_id))
            .join(User, users_services.c.user_id == User.id)
            .where(
                and_(
                    users_services.c.service_id == cls.id,
                    User.removed != True,
                )
            )
            .correlate(cls)
            .scalar_subquery(),
            deferred=False,
        )


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(32), unique=True, index=True)
    key = Column(String(64), unique=True)
    activated = Column(Boolean, nullable=False, default=True)
    enabled = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default=sqlalchemy.sql.true(),
    )
    removed = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default=sqlalchemy.sql.false(),
    )
    services = relationship(
        "Service",
        secondary=users_services,
        back_populates="users",
        lazy="joined",
    )
    inbounds = relationship(
        "Inbound",
        secondary="join(users_services, inbounds_services, inbounds_services.c.service_id == users_services.c.service_id)"
        ".join(Inbound, Inbound.id == inbounds_services.c.inbound_id)",
        viewonly=True,
        distinct_target_key=True,
    )
    used_traffic = Column(BigInteger, default=0)
    lifetime_used_traffic = Column(
        BigInteger, default=0, server_default="0", nullable=False
    )
    traffic_reset_at = Column(DateTime)
    node_usages = relationship(
        "NodeUserUsage",
        back_populates="user",
        cascade="all,delete,delete-orphan",
    )
    data_limit = Column(BigInteger)
    data_limit_reset_strategy = Column(
        Enum(UserDataUsageResetStrategy),
        nullable=False,
        default=UserDataUsageResetStrategy.no_reset,
    )
    device_limit = Column(Integer, nullable=True)
    ip_limit = Column(Integer, nullable=False, default=-1)
    settings = Column(String(1024))
    expire_strategy = Column(
        Enum(UserExpireStrategy),
        nullable=False,
        default=UserExpireStrategy.NEVER,
    )
    expire_date = Column(DateTime)
    usage_duration = Column(BigInteger)
    activation_deadline = Column(DateTime)
    admin_id = Column(Integer, ForeignKey("admins.id"))
    admin = relationship("Admin", back_populates="users")
    sub_updated_at = Column(DateTime)
    sub_last_user_agent = Column(String(512))
    sub_revoked_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    note = Column(String(500))
    online_at = Column(DateTime)
    edit_at = Column(DateTime)

    @property
    def service_ids(self):
        return [service.id for service in self.services]

    @hybrid_property
    def expired(self):
        if self.expire_strategy == "fixed_date":
            return self.expire_date < datetime.utcnow()
        return False

    @expired.expression
    def expired(cls):
        return and_(
            cls.expire_strategy == "fixed_date", cls.expire_date < func.now()
        )

    @hybrid_property
    def data_limit_reached(self):
        if self.data_limit is not None:
            return self.used_traffic >= self.data_limit
        return False

    @data_limit_reached.expression
    def data_limit_reached(cls):
        return and_(
            cls.data_limit.isnot(None), cls.used_traffic >= cls.data_limit
        )

    @hybrid_property
    def is_active(self):
        return (
            self.enabled
            and not self.expired
            and not self.data_limit_reached
            and not self.removed
        )

    @is_active.expression
    def is_active(cls):
        return and_(
            cls.enabled == True,
            ~cls.expired,
            ~cls.data_limit_reached,
            ~cls.removed,
        )

    @property
    def status(self):
        return UserStatus.ACTIVE if self.is_active else UserStatus.INACTIVE

    @property
    def subscription_url(self):
        prefix = (
            self.admin.subscription_url_prefix if self.admin else None
        ) or SUBSCRIPTION_URL_PREFIX
        return (
            prefix.replace("*", secrets.token_hex(8))
            + f"/sub/{self.username}/{self.key}"
        )

    @hybrid_property
    def owner_username(self):
        return self.admin.username if self.admin else None
