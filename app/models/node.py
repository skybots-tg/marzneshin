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


class UserDevicesResponse(BaseModel):
    """Response with user's device history"""
    uid: int
    devices: list[DeviceInfo]


class AllUsersDevicesResponse(BaseModel):
    """Response with all users' device history"""
    users: list[UserDevicesResponse]