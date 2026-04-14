from enum import StrEnum
from typing import Pattern

from pydantic import BaseModel, Field


class ConfigTypes(StrEnum):
    links = "links"
    base64_links = "base64-links"
    xray = "xray"
    sing_box = "sing-box"
    clash = "clash"
    clash_meta = "clash-meta"
    template = "template"
    block = "block"


class SubscriptionRule(BaseModel):
    pattern: Pattern
    result: ConfigTypes


class SubscriptionSettings(BaseModel):
    template_on_acceptance: bool
    profile_title: str
    support_link: str
    update_interval: int
    shuffle_configs: bool = False
    placeholder_if_disabled: bool = True
    placeholder_remark: str = "disabled"
    exclude_unhealthy_nodes: bool = False
    rules: list[SubscriptionRule]


class TelegramSettings(BaseModel):
    token: str
    admin_id: list[int]
    channel_id: int | None


class Settings(BaseModel):
    subscription: SubscriptionSettings
    telegram: TelegramSettings | None


class SSHPinStatus(BaseModel):
    configured: bool
    has_credentials: bool


class SSHPinSetup(BaseModel):
    pin: str = Field(min_length=4, max_length=4, pattern=r"^\d{4}$")


class DatabasePoolConfig(BaseModel):
    pool_size: int = Field(ge=1, le=200)
    max_overflow: int = Field(ge=0, le=200)
    pool_timeout: int = Field(ge=1, le=300)
    pool_recycle: int = Field(ge=60, le=7200)


class DatabasePoolStats(BaseModel):
    pool_size: int
    max_overflow: int
    pool_timeout: int
    pool_recycle: int
    statement_timeout: int
    connect_timeout: int
    checked_out: int
    checked_in: int
    overflow: int
    total_connections: int
    max_connections: int
