from enum import StrEnum, IntEnum

from pydantic import ConfigDict, BaseModel, Field


class BackendConfigFormat(IntEnum):
    PLAIN = 0
    JSON = 1
    YAML = 2


class BackendConfig(BaseModel):
    config: str
    format: BackendConfigFormat


class BackendStats(BaseModel):
    running: bool


class Backend(BaseModel):
    name: str
    backend_type: str
    version: str | None
    running: bool
    model_config = ConfigDict(from_attributes=True)


class NodeStatus(StrEnum):
    healthy = "healthy"
    unhealthy = "unhealthy"
    disabled = "disabled"


class NodeConnectionBackend(StrEnum):
    grpcio = "grpcio"
    grpclib = "grpclib"


class NodeSettings(BaseModel):
    min_node_version: str = "v0.2.0"
    certificate: str


class Node(BaseModel):
    id: int | None = Field(None)
    name: str
    address: str
    port: int = 53042
    connection_backend: NodeConnectionBackend = Field(
        default=NodeConnectionBackend.grpclib
    )
    usage_coefficient: float = Field(ge=0, default=1.0)
    model_config = ConfigDict(from_attributes=True)


class NodeCreate(Node):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "DE node",
                "address": "192.168.1.1",
                "port": 53042,
                "usage_coefficient": 1,
            }
        }
    )


class NodeModify(Node):
    name: str | None = Field(None)
    address: str | None = Field(None)
    port: int | None = Field(None)
    connection_backend: NodeConnectionBackend | None = Field(None)
    status: NodeStatus | None = Field(None)
    usage_coefficient: float | None = Field(None, ge=0)
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "DE node",
                "address": "192.168.1.1",
                "port": 53042,
                "status": "disabled",
                "usage_coefficient": 1.0,
            }
        }
    )


class NodeResponse(Node):
    xray_version: str | None = None
    status: NodeStatus
    message: str | None = None
    model_config = ConfigDict(from_attributes=True)
    inbound_ids: list[int] | None = None
    backends: list[Backend]
    adblock_enabled: bool = False
    address_in_hosts: bool = True


class NodeUsageResponse(BaseModel):
    node_id: int | None = None
    node_name: str
    uplink: int
    downlink: int


class NodesUsageResponse(BaseModel):
    usages: list[NodeUsageResponse]


class DeviceInfo(BaseModel):
    """Device information from node"""
    remote_ip: str
    client_name: str
    user_agent: str | None = None
    protocol: str | None = None
    tls_fingerprint: str | None = None
    first_seen: int  # Unix timestamp
    last_seen: int  # Unix timestamp
    total_usage: int  # Bytes
    uplink: int  # Bytes
    downlink: int  # Bytes
    is_active: bool


class DeviceInfoWithUser(DeviceInfo):
    """Flat device info including user ID, used for paginated listing"""
    uid: int


class UserDevicesResponse(BaseModel):
    """Response with user's device history"""
    uid: int
    devices: list[DeviceInfo]


class AllUsersDevicesResponse(BaseModel):
    """Response with all users' device history"""
    users: list[UserDevicesResponse]


class SSHCredentials(BaseModel):
    """SSH connection credentials for node operations"""
    ssh_user: str = "root"
    ssh_port: int = 22
    ssh_password: str | None = None
    ssh_key: str | None = None


class NodeSystemStats(BaseModel):
    """Snapshot of CPU / RAM / disk / load avg metrics from a node.

    Numbers are intentionally compact and dimensionless on the client
    side: bytes for memory/disk, percent (0-100) for utilisation. The
    snapshot is cached both on the node (``CACHE_TTL_SECONDS`` in
    ``marznode/utils/system_stats.py``) and on the panel (`_TTL` in
    ``app/marznode/system_stats_cache.py``) so frequent UI polling
    never hits the node more than a couple of times per minute.
    """

    cpu_percent: float = Field(ge=0)
    cpu_count: int = Field(ge=0)

    mem_total: int = Field(ge=0)
    mem_used: int = Field(ge=0)
    mem_available: int = Field(ge=0)
    mem_percent: float = Field(ge=0)

    disk_total: int = Field(ge=0)
    disk_used: int = Field(ge=0)
    disk_free: int = Field(ge=0)
    disk_percent: float = Field(ge=0)
    disk_path: str = ""

    load_avg_1: float = Field(ge=0)
    load_avg_5: float = Field(ge=0)
    load_avg_15: float = Field(ge=0)

    uptime_seconds: int = Field(ge=0)
    collected_at: int = Field(ge=0)