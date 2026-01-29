"""Device tracking integration helpers"""
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.db import device_crud
from app.utils.device_fingerprint import (
    build_device_fingerprint,
    guess_client_type,
    extract_client_name,
    normalize_client_name,
)


logger = logging.getLogger(__name__)


def track_user_connection(
    db: Session,
    user_id: int,
    node_id: int,
    remote_ip: str,
    client_name: Optional[str] = None,
    user_agent: Optional[str] = None,
    tls_fingerprint: Optional[str] = None,
    upload_bytes: int = 0,
    download_bytes: int = 0,
    protocol: Optional[str] = None,
    bucket_start: Optional[datetime] = None,
    asn: Optional[int] = None,
    asn_org: Optional[str] = None,
    country_code: Optional[str] = None,
    region: Optional[str] = None,
    city: Optional[str] = None,
    is_datacenter: Optional[bool] = None,
) -> tuple[Optional[int], Optional[int]]:
    """
    Track a user connection and update device records.
    
    This function should be called from the usage tracking worker
    when processing connection reports from marznode.
    
    Args:
        db: Database session
        user_id: User ID
        node_id: Node ID
        remote_ip: Client IP address
        client_name: Client application name
        user_agent: User agent string
        tls_fingerprint: TLS fingerprint
        upload_bytes: Upload traffic bytes
        download_bytes: Download traffic bytes
        protocol: Protocol used (vless, vmess, trojan, etc.)
        bucket_start: Time bucket start for traffic aggregation
        asn: ASN number for geo enrichment
        asn_org: ASN organization name
        country_code: Country code (ISO 2-letter)
        region: Region name
        city: City name
        is_datacenter: Whether IP is from a datacenter
    
    Returns:
        Tuple of (device_id, device_ip_id) or (None, None) if failed
    """
    try:
        # Extract and normalize client name
        if not client_name and user_agent:
            client_name = extract_client_name(user_agent)
        
        client_name = normalize_client_name(client_name)
        
        # Guess client type
        client_type = guess_client_type(client_name, user_agent)
        
        # Build fingerprint
        fingerprint, fingerprint_version = build_device_fingerprint(
            user_id=user_id,
            client_name=client_name,
            tls_fingerprint=tls_fingerprint,
            user_agent=user_agent,
        )
        
        # Get or create device
        device = device_crud.get_device_by_fingerprint(
            db, user_id, fingerprint, fingerprint_version
        )
        
        if not device:
            # Check device limit before creating new device
            from app.db.models import User as DBUser
            user = db.query(DBUser).filter(DBUser.id == user_id).first()
            
            if user and user.device_limit is not None:
                # Count active (non-blocked) devices for this user
                current_device_count = device_crud.get_devices_count(db, user_id, is_blocked=False)
                
                if current_device_count >= user.device_limit:
                    logger.warning(
                        f"Device limit reached for user {user_id}: "
                        f"{current_device_count}/{user.device_limit} devices. "
                        f"Cannot create new device."
                    )
                    # Return None to indicate device limit exceeded
                    return None, None
            
            # Create new device
            device = device_crud.create_device(
                db=db,
                user_id=user_id,
                fingerprint=fingerprint,
                fingerprint_version=fingerprint_version,
                client_name=client_name,
                client_type=client_type,
                node_id=node_id,
            )
            logger.info(
                f"Created new device {device.id} for user {user_id} "
                f"(client: {client_name or 'unknown'})"
            )
            
            # Resync user with nodes to add new device to allowed list
            if user:
                from app.marznode import operations
                operations.update_user(user)
        else:
            # Update last seen
            device = device_crud.update_device(
                db=db,
                device_id=device.id,
                last_node_id=node_id,
            )
        
        # Check if device is blocked
        if device and device.is_blocked:
            logger.warning(
                f"Connection from blocked device {device.id} "
                f"for user {user_id}, IP {remote_ip}"
            )
            # You can add logic here to reject the connection
            # by returning None or raising an exception
        
        # Update device IP statistics
        device_ip = device_crud.update_device_ip_stats(
            db=db,
            device_id=device.id,
            ip=remote_ip,
            upload_bytes=upload_bytes,
            download_bytes=download_bytes,
            increment_connects=True,
            asn=asn,
            asn_org=asn_org,
            country_code=country_code,
            region=region,
            city=city,
            is_datacenter=is_datacenter,
        )
        
        # Update last_ip_id on device if this is the most recent IP
        if device_ip and not device.last_ip_id:
            device_crud.update_device(
                db=db,
                device_id=device.id,
                last_ip_id=device_ip.id,
            )
        
        # Update traffic aggregates
        if bucket_start:
            device_crud.create_or_update_traffic(
                db=db,
                device_id=device.id,
                user_id=user_id,
                node_id=node_id,
                bucket_start=bucket_start,
                upload_bytes=upload_bytes,
                download_bytes=download_bytes,
                connect_count=1,
            )
        
        return device.id, device_ip.id if device_ip else None
        
    except Exception as e:
        logger.error(f"Error tracking user connection: {e}", exc_info=True)
        db.rollback()
        return None, None


def is_device_blocked(db: Session, user_id: int, fingerprint: str) -> bool:
    """
    Check if a device is blocked.
    
    Args:
        db: Database session
        user_id: User ID
        fingerprint: Device fingerprint
    
    Returns:
        True if device is blocked, False otherwise
    """
    device = device_crud.get_device_by_fingerprint(db, user_id, fingerprint, 1)
    return device.is_blocked if device else False


def get_user_active_devices_count(
    db: Session,
    user_id: int,
    hours: int = 24
) -> int:
    """
    Get count of user's active devices in the last N hours.
    
    Args:
        db: Database session
        user_id: User ID
        hours: Time window in hours
    
    Returns:
        Count of active devices
    """
    from datetime import timedelta
    now = datetime.utcnow()
    threshold = now - timedelta(hours=hours)
    
    devices = device_crud.get_user_devices(db, user_id, limit=1000)
    active_count = sum(1 for d in devices if d.last_seen_at >= threshold)
    
    return active_count


def check_device_limit(
    db: Session,
    user_id: int,
    max_devices: int,
    hours: int = 24
) -> tuple[bool, int]:
    """
    Check if user exceeds device limit.
    
    Args:
        db: Database session
        user_id: User ID
        max_devices: Maximum allowed devices
        hours: Time window for "active" devices
    
    Returns:
        Tuple of (is_within_limit, current_count)
    """
    active_count = get_user_active_devices_count(db, user_id, hours)
    return active_count < max_devices, active_count


def detect_suspicious_activity(
    db: Session,
    user_id: int,
    device_id: int
) -> tuple[bool, list[str]]:
    """
    Detect suspicious device activity.
    
    Checks for:
    - Multiple countries in short time
    - Datacenter IPs
    - Rapid IP changes
    
    Args:
        db: Database session
        user_id: User ID
        device_id: Device ID
    
    Returns:
        Tuple of (is_suspicious, reasons)
    """
    reasons = []
    
    # Get device IPs
    ips = device_crud.get_device_ips(db, device_id, limit=100)
    
    if not ips:
        return False, []
    
    # Check for datacenter IPs
    datacenter_ips = [ip for ip in ips if ip.is_datacenter]
    if len(datacenter_ips) > len(ips) * 0.5:  # More than 50% datacenter
        reasons.append("High datacenter IP usage")
    
    # Check for multiple countries
    countries = set(ip.country_code for ip in ips if ip.country_code)
    if len(countries) > 5:
        reasons.append(f"Multiple countries ({len(countries)})")
    
    # Check for rapid IP changes (more than 20 IPs in last 24h)
    from datetime import timedelta
    now = datetime.utcnow()
    recent_threshold = now - timedelta(hours=24)
    recent_ips = [ip for ip in ips if ip.last_seen_at >= recent_threshold]
    if len(recent_ips) > 20:
        reasons.append(f"Rapid IP changes ({len(recent_ips)} in 24h)")
    
    return len(reasons) > 0, reasons

