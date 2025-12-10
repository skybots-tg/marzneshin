from datetime import datetime
from ipaddress import IPv4Address, IPv6Address
from typing import Union, Optional, Annotated

from pydantic import BaseModel, ConfigDict, Field


IPvAnyAddress = Union[IPv4Address, IPv6Address]


class DeviceIPBase(BaseModel):
    """Base schema for device IP"""
    ip: IPvAnyAddress
    first_seen_at: datetime
    last_seen_at: datetime
    connect_count: int = 0
    upload_bytes: int = 0
    download_bytes: int = 0
    
    model_config = ConfigDict(from_attributes=True)


class DeviceIP(DeviceIPBase):
    """Device IP with optional geo/ASN data"""
    id: int
    country_code: Optional[str] = None
    asn: Optional[int] = None
    asn_org: Optional[str] = None
    region: Optional[str] = None
    city: Optional[str] = None
    is_datacenter: Optional[bool] = None


class DeviceIPResponse(DeviceIP):
    """Full device IP response"""
    pass


# Device Base Models
class UserDeviceBase(BaseModel):
    """Base schema for user device"""
    fingerprint: str
    fingerprint_version: int = 1
    display_name: Optional[str] = None
    client_name: Optional[str] = None
    client_type: str = "other"
    
    model_config = ConfigDict(from_attributes=True)


class UserDevice(UserDeviceBase):
    """User device with core fields"""
    id: int
    user_id: int
    first_seen_at: datetime
    last_seen_at: datetime
    last_node_id: Optional[int] = None
    is_blocked: bool = False
    trust_level: int = 0


class UserDeviceResponse(UserDevice):
    """Full user device response with related data"""
    last_ip: Optional[DeviceIP] = None
    total_upload_bytes: int = 0
    total_download_bytes: int = 0
    total_connect_count: int = 0
    ips: list[DeviceIP] = []


class UserDeviceListResponse(UserDevice):
    """Simplified device response for list views"""
    total_upload_bytes: int = 0
    total_download_bytes: int = 0
    total_connect_count: int = 0
    ip_count: int = 0


# Device Create/Modify
class UserDeviceCreate(BaseModel):
    """Create a new device"""
    user_id: int
    fingerprint: str
    fingerprint_version: int = 1
    display_name: Optional[str] = None
    client_name: Optional[str] = None
    client_type: str = "other"
    first_ip: Optional[IPvAnyAddress] = None
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "user_id": 1,
                "fingerprint": "abc123...",
                "fingerprint_version": 1,
                "client_name": "v2rayNG",
                "client_type": "android",
                "display_name": "My Phone",
            }
        }
    )


class UserDeviceModify(BaseModel):
    """Modify device settings"""
    display_name: Optional[str] = None
    is_blocked: Optional[bool] = None
    trust_level: Optional[int] = None
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "display_name": "Work Laptop",
                "trust_level": 1,
            }
        }
    )


# Traffic Models
class DeviceTraffic(BaseModel):
    """Traffic data for a device"""
    bucket_start: datetime
    bucket_seconds: int
    upload_bytes: int
    download_bytes: int
    connect_count: int
    node_id: int
    
    model_config = ConfigDict(from_attributes=True)


class DeviceTrafficResponse(BaseModel):
    """Aggregated traffic response"""
    device_id: int
    user_id: int
    traffic: list[DeviceTraffic]
    total_upload: int
    total_download: int
    total_connects: int


# Statistics Models
class DeviceStatistics(BaseModel):
    """Device usage statistics"""
    device_id: int
    total_traffic: int
    upload_bytes: int
    download_bytes: int
    connect_count: int
    ip_count: int
    first_seen_at: datetime
    last_seen_at: datetime
    countries: list[str] = []
    is_suspicious: bool = False


class UserDevicesStatistics(BaseModel):
    """Aggregated statistics for all user devices"""
    user_id: int
    total_devices: int
    active_devices: int  # devices seen in last 24h
    blocked_devices: int
    total_ips: int
    unique_countries: list[str] = []
    total_traffic: int
    suspicious_devices: int = 0


# Connection Log (optional feature)
class ConnectionLogBase(BaseModel):
    """Base connection log entry"""
    user_id: int
    device_id: Optional[int] = None
    node_id: int
    ip: IPvAnyAddress
    remote_port: Optional[int] = None
    protocol: Optional[str] = None
    inbound_name: Optional[str] = None
    started_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class ConnectionLog(ConnectionLogBase):
    """Full connection log entry"""
    id: int
    ended_at: Optional[datetime] = None
    upload_bytes: Optional[int] = None
    download_bytes: Optional[int] = None
    close_reason: Optional[str] = None


# Device IP Create (internal use)
class DeviceIPCreate(BaseModel):
    """Create device IP record"""
    device_id: int
    ip: IPvAnyAddress
    first_seen_at: datetime
    asn: Optional[int] = None
    asn_org: Optional[str] = None
    country_code: Optional[str] = None
    region: Optional[str] = None
    city: Optional[str] = None
    is_datacenter: Optional[bool] = None


class DeviceIPUpdate(BaseModel):
    """Update device IP statistics"""
    last_seen_at: datetime
    connect_count: Optional[int] = None
    upload_bytes: Optional[int] = None
    download_bytes: Optional[int] = None


# Device Traffic Create (internal use)
class DeviceTrafficCreate(BaseModel):
    """Create traffic aggregate"""
    device_id: int
    user_id: int
    node_id: int
    bucket_start: datetime
    bucket_seconds: int = 300
    upload_bytes: int = 0
    download_bytes: int = 0
    connect_count: int = 0


# Query filters
class DeviceFilters(BaseModel):
    """Filters for device queries"""
    user_id: Optional[int] = None
    ip: Optional[str] = None
    node_id: Optional[int] = None
    country_code: Optional[str] = None
    is_blocked: Optional[bool] = None
    is_datacenter: Optional[bool] = None
    client_type: Optional[str] = None
    from_date: Optional[datetime] = None
    to_date: Optional[datetime] = None


class DeviceIPFilters(BaseModel):
    """Filters for device IP queries"""
    device_id: Optional[int] = None
    ip: Optional[str] = None
    country_code: Optional[str] = None
    is_datacenter: Optional[bool] = None
    from_date: Optional[datetime] = None
    to_date: Optional[datetime] = None

