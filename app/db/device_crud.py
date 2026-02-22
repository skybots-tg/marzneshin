"""CRUD operations for device tracking"""
from datetime import datetime, timedelta
from typing import Optional, List
from ipaddress import IPv4Address, IPv6Address, ip_address

from sqlalchemy import func, desc, and_, or_
from sqlalchemy.orm import Session, joinedload

from app.db.models import UserDevice, UserDeviceIP, UserDeviceTraffic, User, Node


# ============================================================================
# UserDevice CRUD
# ============================================================================

def get_device_by_id(db: Session, device_id: int) -> Optional[UserDevice]:
    """Get device by ID"""
    return db.query(UserDevice).filter(UserDevice.id == device_id).first()


def get_device_by_fingerprint(
    db: Session,
    user_id: int,
    fingerprint: str,
    fingerprint_version: int = 1
) -> Optional[UserDevice]:
    """Get device by fingerprint"""
    return db.query(UserDevice).filter(
        UserDevice.user_id == user_id,
        UserDevice.fingerprint == fingerprint,
        UserDevice.fingerprint_version == fingerprint_version
    ).first()


def get_user_devices(
    db: Session,
    user_id: int,
    offset: int = 0,
    limit: int = 100,
    is_blocked: Optional[bool] = None
) -> List[UserDevice]:
    """Get all devices for a user"""
    query = db.query(UserDevice).filter(UserDevice.user_id == user_id)
    
    if is_blocked is not None:
        query = query.filter(UserDevice.is_blocked == is_blocked)
    
    return query.order_by(desc(UserDevice.last_seen_at)).offset(offset).limit(limit).all()


def get_devices_count(db: Session, user_id: int, is_blocked: Optional[bool] = None) -> int:
    """Count devices for a user"""
    query = db.query(func.count(UserDevice.id)).filter(UserDevice.user_id == user_id)
    
    if is_blocked is not None:
        query = query.filter(UserDevice.is_blocked == is_blocked)
    
    return query.scalar()


def create_device(
    db: Session,
    user_id: int,
    fingerprint: str,
    fingerprint_version: int = 1,
    client_name: Optional[str] = None,
    client_type: str = "other",
    display_name: Optional[str] = None,
    node_id: Optional[int] = None,
    auto_commit: bool = True,
) -> UserDevice:
    """Create a new device. Set auto_commit=False for batch operations."""
    now = datetime.utcnow()
    device = UserDevice(
        user_id=user_id,
        fingerprint=fingerprint,
        fingerprint_version=fingerprint_version,
        client_name=client_name,
        client_type=client_type,
        display_name=display_name,
        first_seen_at=now,
        last_seen_at=now,
        last_node_id=node_id,
    )
    db.add(device)
    if auto_commit:
        db.commit()
        db.refresh(device)
    else:
        db.flush()  # Get the ID without committing
    return device


def update_device(
    db: Session,
    device_id: int,
    display_name: Optional[str] = None,
    is_blocked: Optional[bool] = None,
    trust_level: Optional[int] = None,
    last_node_id: Optional[int] = None,
    last_ip_id: Optional[int] = None,
    auto_commit: bool = True,
) -> Optional[UserDevice]:
    """Update device information. Set auto_commit=False for batch operations."""
    device = get_device_by_id(db, device_id)
    if not device:
        return None
    
    if display_name is not None:
        device.display_name = display_name
    if is_blocked is not None:
        device.is_blocked = is_blocked
    if trust_level is not None:
        device.trust_level = trust_level
    if last_node_id is not None:
        device.last_node_id = last_node_id
    if last_ip_id is not None:
        device.last_ip_id = last_ip_id
    
    device.last_seen_at = datetime.utcnow()
    if auto_commit:
        db.commit()
        db.refresh(device)
    return device


def delete_device(db: Session, device_id: int) -> bool:
    """Delete a device and all related data"""
    device = get_device_by_id(db, device_id)
    if not device:
        return False
    
    db.delete(device)
    db.commit()
    return True


def get_devices_for_users_batch(
    db: Session,
    user_ids: List[int],
    is_blocked: Optional[bool] = None
) -> dict[int, List[UserDevice]]:
    """Get devices for multiple users in a single query, grouped by user_id."""
    if not user_ids:
        return {}
    
    query = db.query(UserDevice).filter(UserDevice.user_id.in_(user_ids))
    
    if is_blocked is not None:
        query = query.filter(UserDevice.is_blocked == is_blocked)
    
    devices = query.all()
    
    result: dict[int, List[UserDevice]] = {}
    for device in devices:
        if device.user_id not in result:
            result[device.user_id] = []
        result[device.user_id].append(device)
    
    return result


def get_devices_by_ip(
    db: Session,
    ip: str,
    offset: int = 0,
    limit: int = 100
) -> List[UserDevice]:
    """Get all devices that used a specific IP"""
    return db.query(UserDevice).join(UserDeviceIP).filter(
        UserDeviceIP.ip == ip
    ).distinct().order_by(desc(UserDeviceIP.last_seen_at)).offset(offset).limit(limit).all()


def search_devices(
    db: Session,
    user_id: Optional[int] = None,
    node_id: Optional[int] = None,
    ip: Optional[str] = None,
    country_code: Optional[str] = None,
    is_blocked: Optional[bool] = None,
    is_datacenter: Optional[bool] = None,
    client_type: Optional[str] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    offset: int = 0,
    limit: int = 100
) -> List[UserDevice]:
    """Search devices with filters"""
    query = db.query(UserDevice)
    
    if user_id:
        query = query.filter(UserDevice.user_id == user_id)
    
    if node_id:
        query = query.filter(UserDevice.last_node_id == node_id)
    
    if is_blocked is not None:
        query = query.filter(UserDevice.is_blocked == is_blocked)
    
    if client_type:
        query = query.filter(UserDevice.client_type == client_type)
    
    if from_date:
        query = query.filter(UserDevice.last_seen_at >= from_date)
    
    if to_date:
        query = query.filter(UserDevice.last_seen_at <= to_date)
    
    # IP and geo filters require join
    if ip or country_code or is_datacenter is not None:
        query = query.join(UserDeviceIP)
        
        if ip:
            query = query.filter(UserDeviceIP.ip == ip)
        
        if country_code:
            query = query.filter(UserDeviceIP.country_code == country_code)
        
        if is_datacenter is not None:
            query = query.filter(UserDeviceIP.is_datacenter == is_datacenter)
        
        # Prevent duplicates when device has multiple matching IPs
        query = query.distinct()
    
    return query.order_by(desc(UserDevice.last_seen_at)).offset(offset).limit(limit).all()


# ============================================================================
# UserDeviceIP CRUD
# ============================================================================

def get_device_ip_by_id(db: Session, ip_id: int) -> Optional[UserDeviceIP]:
    """Get device IP by ID"""
    return db.query(UserDeviceIP).filter(UserDeviceIP.id == ip_id).first()


def get_device_ip(
    db: Session,
    device_id: int,
    ip: str
) -> Optional[UserDeviceIP]:
    """Get specific IP for a device"""
    return db.query(UserDeviceIP).filter(
        UserDeviceIP.device_id == device_id,
        UserDeviceIP.ip == ip
    ).first()


def get_device_ips(
    db: Session,
    device_id: int,
    offset: int = 0,
    limit: int = 100
) -> List[UserDeviceIP]:
    """Get all IPs for a device"""
    return db.query(UserDeviceIP).filter(
        UserDeviceIP.device_id == device_id
    ).order_by(desc(UserDeviceIP.last_seen_at)).offset(offset).limit(limit).all()


def create_device_ip(
    db: Session,
    device_id: int,
    ip: str,
    asn: Optional[int] = None,
    asn_org: Optional[str] = None,
    country_code: Optional[str] = None,
    region: Optional[str] = None,
    city: Optional[str] = None,
    is_datacenter: Optional[bool] = None,
    auto_commit: bool = True,
) -> UserDeviceIP:
    """Create a new device IP record. Set auto_commit=False for batch operations."""
    now = datetime.utcnow()
    device_ip = UserDeviceIP(
        device_id=device_id,
        ip=ip,
        first_seen_at=now,
        last_seen_at=now,
        connect_count=1,
        asn=asn,
        asn_org=asn_org,
        country_code=country_code,
        region=region,
        city=city,
        is_datacenter=is_datacenter,
    )
    db.add(device_ip)
    if auto_commit:
        db.commit()
        db.refresh(device_ip)
    else:
        db.flush()
    return device_ip


def update_device_ip_stats(
    db: Session,
    device_id: int,
    ip: str,
    upload_bytes: int = 0,
    download_bytes: int = 0,
    increment_connects: bool = True,
    asn: Optional[int] = None,
    asn_org: Optional[str] = None,
    country_code: Optional[str] = None,
    region: Optional[str] = None,
    city: Optional[str] = None,
    is_datacenter: Optional[bool] = None,
    auto_commit: bool = True,
) -> UserDeviceIP:
    """Update device IP statistics. Set auto_commit=False for batch operations."""
    device_ip = get_device_ip(db, device_id, ip)
    
    if not device_ip:
        # Create if doesn't exist - pass auto_commit=False since we'll commit at the end
        device_ip = create_device_ip(
            db, device_id, ip, asn, asn_org, country_code, region, city, is_datacenter,
            auto_commit=False
        )
    
    # Update stats
    device_ip.last_seen_at = datetime.utcnow()
    device_ip.upload_bytes += upload_bytes
    device_ip.download_bytes += download_bytes
    
    if increment_connects:
        device_ip.connect_count += 1
    
    # Update geo data if provided
    if asn and not device_ip.asn:
        device_ip.asn = asn
    if asn_org and not device_ip.asn_org:
        device_ip.asn_org = asn_org
    if country_code and not device_ip.country_code:
        device_ip.country_code = country_code
    if region and not device_ip.region:
        device_ip.region = region
    if city and not device_ip.city:
        device_ip.city = city
    if is_datacenter is not None and device_ip.is_datacenter is None:
        device_ip.is_datacenter = is_datacenter
    
    if auto_commit:
        db.commit()
        db.refresh(device_ip)
    return device_ip


def get_ips_by_device_ids(db: Session, device_ids: List[int]) -> dict[int, List[UserDeviceIP]]:
    """Get IPs grouped by device IDs"""
    if not device_ids:
        return {}
    
    ips = db.query(UserDeviceIP).filter(
        UserDeviceIP.device_id.in_(device_ids)
    ).order_by(UserDeviceIP.device_id, desc(UserDeviceIP.last_seen_at)).all()
    
    result = {}
    for ip in ips:
        if ip.device_id not in result:
            result[ip.device_id] = []
        result[ip.device_id].append(ip)
    
    return result


# ============================================================================
# UserDeviceTraffic CRUD
# ============================================================================

def get_device_traffic(
    db: Session,
    device_id: int,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    node_id: Optional[int] = None,
    offset: int = 0,
    limit: int = 1000
) -> List[UserDeviceTraffic]:
    """Get traffic records for a device"""
    query = db.query(UserDeviceTraffic).filter(
        UserDeviceTraffic.device_id == device_id
    )
    
    if from_date:
        query = query.filter(UserDeviceTraffic.bucket_start >= from_date)
    
    if to_date:
        query = query.filter(UserDeviceTraffic.bucket_start <= to_date)
    
    if node_id:
        query = query.filter(UserDeviceTraffic.node_id == node_id)
    
    return query.order_by(UserDeviceTraffic.bucket_start).offset(offset).limit(limit).all()


def get_user_traffic(
    db: Session,
    user_id: int,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    node_id: Optional[int] = None,
) -> List[UserDeviceTraffic]:
    """Get all traffic records for a user"""
    query = db.query(UserDeviceTraffic).filter(
        UserDeviceTraffic.user_id == user_id
    )
    
    if from_date:
        query = query.filter(UserDeviceTraffic.bucket_start >= from_date)
    
    if to_date:
        query = query.filter(UserDeviceTraffic.bucket_start <= to_date)
    
    if node_id:
        query = query.filter(UserDeviceTraffic.node_id == node_id)
    
    return query.order_by(UserDeviceTraffic.bucket_start).all()


def create_or_update_traffic(
    db: Session,
    device_id: int,
    user_id: int,
    node_id: int,
    bucket_start: datetime,
    bucket_seconds: int = 300,
    upload_bytes: int = 0,
    download_bytes: int = 0,
    connect_count: int = 0,
    auto_commit: bool = True,
) -> UserDeviceTraffic:
    """Create or update traffic aggregate. Set auto_commit=False for batch operations."""
    traffic = db.query(UserDeviceTraffic).filter(
        UserDeviceTraffic.device_id == device_id,
        UserDeviceTraffic.node_id == node_id,
        UserDeviceTraffic.bucket_start == bucket_start
    ).first()
    
    if not traffic:
        traffic = UserDeviceTraffic(
            device_id=device_id,
            user_id=user_id,
            node_id=node_id,
            bucket_start=bucket_start,
            bucket_seconds=bucket_seconds,
            upload_bytes=0,
            download_bytes=0,
            connect_count=0,
        )
        db.add(traffic)
    
    traffic.upload_bytes += upload_bytes
    traffic.download_bytes += download_bytes
    traffic.connect_count += connect_count
    
    if auto_commit:
        db.commit()
        db.refresh(traffic)
    return traffic


def get_device_total_traffic(db: Session, device_id: int) -> dict:
    """Get total traffic statistics for a device"""
    result = db.query(
        func.sum(UserDeviceTraffic.upload_bytes).label('total_upload'),
        func.sum(UserDeviceTraffic.download_bytes).label('total_download'),
        func.sum(UserDeviceTraffic.connect_count).label('total_connects'),
    ).filter(
        UserDeviceTraffic.device_id == device_id
    ).first()
    
    return {
        'total_upload_bytes': result.total_upload or 0,
        'total_download_bytes': result.total_download or 0,
        'total_connect_count': result.total_connects or 0,
    }


# ============================================================================
# Statistics and Analytics
# ============================================================================

def get_user_device_statistics(db: Session, user_id: int) -> dict:
    """Get aggregated statistics for all user devices"""
    now = datetime.utcnow()
    last_24h = now - timedelta(hours=24)
    
    # Total devices
    total_devices = db.query(func.count(UserDevice.id)).filter(
        UserDevice.user_id == user_id
    ).scalar()
    
    # Active devices (seen in last 24h)
    active_devices = db.query(func.count(UserDevice.id)).filter(
        UserDevice.user_id == user_id,
        UserDevice.last_seen_at >= last_24h
    ).scalar()
    
    # Blocked devices
    blocked_devices = db.query(func.count(UserDevice.id)).filter(
        UserDevice.user_id == user_id,
        UserDevice.is_blocked == True
    ).scalar()
    
    # Total unique IPs
    total_ips = db.query(func.count(UserDeviceIP.id)).join(UserDevice).filter(
        UserDevice.user_id == user_id
    ).scalar()
    
    # Unique countries
    countries = db.query(UserDeviceIP.country_code).join(UserDevice).filter(
        UserDevice.user_id == user_id,
        UserDeviceIP.country_code.isnot(None)
    ).distinct().all()
    unique_countries = [c[0] for c in countries if c[0]]
    
    # Total traffic
    traffic = db.query(
        func.sum(UserDeviceTraffic.upload_bytes).label('upload'),
        func.sum(UserDeviceTraffic.download_bytes).label('download'),
    ).filter(
        UserDeviceTraffic.user_id == user_id
    ).first()
    
    total_traffic = (traffic.upload or 0) + (traffic.download or 0)
    
    return {
        'user_id': user_id,
        'total_devices': total_devices,
        'active_devices': active_devices,
        'blocked_devices': blocked_devices,
        'total_ips': total_ips,
        'unique_countries': unique_countries,
        'total_traffic': total_traffic,
    }

