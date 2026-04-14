from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class DnsProvider(StrEnum):
    adguard_home_local = "adguard_home_local"
    adguard_dns_public = "adguard_dns_public"
    nextdns = "nextdns"
    cloudflare_security = "cloudflare_security"
    custom = "custom"


class NodeFilteringConfigBase(BaseModel):
    adblock_enabled: bool = False
    dns_provider: DnsProvider = DnsProvider.adguard_dns_public
    dns_address: str | None = None
    adguard_home_port: int = Field(default=5353, ge=1, le=65535)

    model_config = ConfigDict(from_attributes=True)


class NodeFilteringConfigResponse(NodeFilteringConfigBase):
    adguard_home_installed: bool = False


class NodeFilteringConfigUpdate(BaseModel):
    adblock_enabled: bool | None = None
    dns_provider: DnsProvider | None = None
    dns_address: str | None = None
    adguard_home_port: int | None = Field(default=None, ge=1, le=65535)


class SSHCredentialsStore(BaseModel):
    ssh_user: str = "root"
    ssh_port: int = Field(default=22, ge=1, le=65535)
    ssh_password: str | None = None
    ssh_key: str | None = None
    pin: str = Field(min_length=4, max_length=4, pattern=r"^\d{4}$")


class SSHCredentialsInfo(BaseModel):
    """Non-sensitive info about stored credentials."""
    exists: bool
    ssh_user: str | None = None
    ssh_port: int | None = None


class SSHCredentialsWithPin(BaseModel):
    pin: str = Field(min_length=4, max_length=4, pattern=r"^\d{4}$")
