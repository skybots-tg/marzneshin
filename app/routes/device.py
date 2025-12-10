"""Device tracking and management API routes"""
import logging
from datetime import datetime, timedelta
from typing import Optional, Annotated

from fastapi import APIRouter, HTTPException, Query, Path
from fastapi_pagination import Page, Params
from fastapi_pagination.ext.sqlalchemy import paginate as sqlalchemy_paginate

from app.db import device_crud
from app.db.models import UserDevice as DBUserDevice, User as DBUser
from app.dependencies import (
    DBDep,
    AdminDep,
    SudoAdminDep,
    UserDep,
)
from app.models.device import (
    UserDeviceResponse,
    UserDeviceListResponse,
    UserDeviceModify,
    DeviceIP,
    DeviceTraffic,
    DeviceTrafficResponse,
    UserDevicesStatistics,
    DeviceStatistics,
)


logger = logging.getLogger(__name__)
router = APIRouter(tags=["Devices"])


# ============================================================================
# Admin Routes - Full Access
# ============================================================================

@router.get("/admin/devices", response_model=Page[UserDeviceListResponse])
def admin_get_all_devices(
    db: DBDep,
    admin: SudoAdminDep,
    user_id: Optional[int] = Query(None),
    node_id: Optional[int] = Query(None),
    ip: Optional[str] = Query(None),
    country_code: Optional[str] = Query(None),
    is_blocked: Optional[bool] = Query(None),
    is_datacenter: Optional[bool] = Query(None),
    client_type: Optional[str] = Query(None),
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
):
    """
    Get all devices (admin only) with optional filters.
    Supports filtering by user, IP, country, node, etc.
    """
    devices = device_crud.search_devices(
        db=db,
        user_id=user_id,
        node_id=node_id,
        ip=ip,
        country_code=country_code,
        is_blocked=is_blocked,
        is_datacenter=is_datacenter,
        client_type=client_type,
        from_date=from_date,
        to_date=to_date,
    )
    
    # Enrich with statistics
    result = []
    for device in devices:
        stats = device_crud.get_device_total_traffic(db, device.id)
        ip_count = len(device_crud.get_device_ips(db, device.id, limit=1000))
        
        result.append(
            UserDeviceListResponse(
                **device.__dict__,
                total_upload_bytes=stats['total_upload_bytes'],
                total_download_bytes=stats['total_download_bytes'],
                total_connect_count=stats['total_connect_count'],
                ip_count=ip_count,
            )
        )
    
    # Manual pagination
    params = Params()
    start = (params.page - 1) * params.size
    end = start + params.size
    
    return Page(
        items=result[start:end],
        total=len(result),
        page=params.page,
        size=params.size,
    )


@router.get("/admin/users/{user_id}/devices", response_model=list[UserDeviceListResponse])
def admin_get_user_devices(
    db: DBDep,
    admin: AdminDep,
    user_id: int = Path(...),
    is_blocked: Optional[bool] = Query(None),
):
    """
    Get all devices for a specific user (admin only).
    """
    # Check if user exists
    user = db.query(DBUser).filter(DBUser.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Check permissions (sudo or owner)
    if not admin.is_sudo and user.admin_id != admin.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    devices = device_crud.get_user_devices(db, user_id, is_blocked=is_blocked)
    
    result = []
    for device in devices:
        stats = device_crud.get_device_total_traffic(db, device.id)
        ip_count = len(device_crud.get_device_ips(db, device.id, limit=1000))
        
        result.append(
            UserDeviceListResponse(
                **device.__dict__,
                total_upload_bytes=stats['total_upload_bytes'],
                total_download_bytes=stats['total_download_bytes'],
                total_connect_count=stats['total_connect_count'],
                ip_count=ip_count,
            )
        )
    
    return result


@router.get("/admin/users/{user_id}/devices/{device_id}", response_model=UserDeviceResponse)
def admin_get_device_details(
    db: DBDep,
    admin: AdminDep,
    user_id: int = Path(...),
    device_id: int = Path(...),
):
    """
    Get detailed information about a specific device (admin only).
    """
    device = device_crud.get_device_by_id(db, device_id)
    if not device or device.user_id != user_id:
        raise HTTPException(status_code=404, detail="Device not found")
    
    # Check permissions
    user = db.query(DBUser).filter(DBUser.id == user_id).first()
    if not admin.is_sudo and (not user or user.admin_id != admin.id):
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Get statistics
    stats = device_crud.get_device_total_traffic(db, device.id)
    ips = device_crud.get_device_ips(db, device.id)
    
    # Get last IP details
    last_ip = None
    if device.last_ip_id:
        last_ip_obj = device_crud.get_device_ip_by_id(db, device.last_ip_id)
        if last_ip_obj:
            last_ip = DeviceIP.model_validate(last_ip_obj)
    
    return UserDeviceResponse(
        **device.__dict__,
        last_ip=last_ip,
        total_upload_bytes=stats['total_upload_bytes'],
        total_download_bytes=stats['total_download_bytes'],
        total_connect_count=stats['total_connect_count'],
        ips=[DeviceIP.model_validate(ip) for ip in ips],
    )


@router.patch("/admin/users/{user_id}/devices/{device_id}", response_model=UserDeviceResponse)
def admin_update_device(
    db: DBDep,
    admin: AdminDep,
    modifications: UserDeviceModify,
    user_id: int = Path(...),
    device_id: int = Path(...),
):
    """
    Update device settings (admin only).
    Can modify display_name, is_blocked, trust_level.
    """
    device = device_crud.get_device_by_id(db, device_id)
    if not device or device.user_id != user_id:
        raise HTTPException(status_code=404, detail="Device not found")
    
    # Check permissions
    user = db.query(DBUser).filter(DBUser.id == user_id).first()
    if not admin.is_sudo and (not user or user.admin_id != admin.id):
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Update device
    updated_device = device_crud.update_device(
        db=db,
        device_id=device_id,
        display_name=modifications.display_name,
        is_blocked=modifications.is_blocked,
        trust_level=modifications.trust_level,
    )
    
    if not updated_device:
        raise HTTPException(status_code=500, detail="Failed to update device")
    
    # Get full response
    stats = device_crud.get_device_total_traffic(db, device.id)
    ips = device_crud.get_device_ips(db, device.id)
    
    last_ip = None
    if updated_device.last_ip_id:
        last_ip_obj = device_crud.get_device_ip_by_id(db, updated_device.last_ip_id)
        if last_ip_obj:
            last_ip = DeviceIP.model_validate(last_ip_obj)
    
    return UserDeviceResponse(
        **updated_device.__dict__,
        last_ip=last_ip,
        total_upload_bytes=stats['total_upload_bytes'],
        total_download_bytes=stats['total_download_bytes'],
        total_connect_count=stats['total_connect_count'],
        ips=[DeviceIP.model_validate(ip) for ip in ips],
    )


@router.delete("/admin/users/{user_id}/devices/{device_id}", status_code=204)
def admin_delete_device(
    db: DBDep,
    admin: AdminDep,
    user_id: int = Path(...),
    device_id: int = Path(...),
):
    """
    Delete a device and all its data (admin only).
    """
    device = device_crud.get_device_by_id(db, device_id)
    if not device or device.user_id != user_id:
        raise HTTPException(status_code=404, detail="Device not found")
    
    # Check permissions
    user = db.query(DBUser).filter(DBUser.id == user_id).first()
    if not admin.is_sudo and (not user or user.admin_id != admin.id):
        raise HTTPException(status_code=403, detail="Access denied")
    
    success = device_crud.delete_device(db, device_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete device")
    
    return None


@router.get("/admin/users/{user_id}/devices/{device_id}/traffic", response_model=DeviceTrafficResponse)
def admin_get_device_traffic(
    db: DBDep,
    admin: AdminDep,
    user_id: int = Path(...),
    device_id: int = Path(...),
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
    node_id: Optional[int] = Query(None),
):
    """
    Get traffic history for a device (admin only).
    """
    device = device_crud.get_device_by_id(db, device_id)
    if not device or device.user_id != user_id:
        raise HTTPException(status_code=404, detail="Device not found")
    
    # Check permissions
    user = db.query(DBUser).filter(DBUser.id == user_id).first()
    if not admin.is_sudo and (not user or user.admin_id != admin.id):
        raise HTTPException(status_code=403, detail="Access denied")
    
    traffic = device_crud.get_device_traffic(
        db=db,
        device_id=device_id,
        from_date=from_date,
        to_date=to_date,
        node_id=node_id,
    )
    
    total_upload = sum(t.upload_bytes for t in traffic)
    total_download = sum(t.download_bytes for t in traffic)
    total_connects = sum(t.connect_count for t in traffic)
    
    return DeviceTrafficResponse(
        device_id=device_id,
        user_id=user_id,
        traffic=[DeviceTraffic.model_validate(t) for t in traffic],
        total_upload=total_upload,
        total_download=total_download,
        total_connects=total_connects,
    )


@router.get("/admin/users/{user_id}/devices/statistics", response_model=UserDevicesStatistics)
def admin_get_user_device_statistics(
    db: DBDep,
    admin: AdminDep,
    user_id: int = Path(...),
):
    """
    Get aggregated statistics for all user devices (admin only).
    """
    # Check if user exists
    user = db.query(DBUser).filter(DBUser.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Check permissions
    if not admin.is_sudo and user.admin_id != admin.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    stats = device_crud.get_user_device_statistics(db, user_id)
    
    return UserDevicesStatistics(**stats)


# ============================================================================
# User Routes - Self-Service
# ============================================================================

@router.get("/user/devices", response_model=list[UserDeviceListResponse])
def user_get_own_devices(
    db: DBDep,
    user: UserDep,
    is_blocked: Optional[bool] = Query(None),
):
    """
    Get current user's devices.
    Limited information compared to admin view.
    """
    devices = device_crud.get_user_devices(db, user.id, is_blocked=is_blocked)
    
    result = []
    for device in devices:
        stats = device_crud.get_device_total_traffic(db, device.id)
        ip_count = len(device_crud.get_device_ips(db, device.id, limit=1000))
        
        result.append(
            UserDeviceListResponse(
                **device.__dict__,
                total_upload_bytes=stats['total_upload_bytes'],
                total_download_bytes=stats['total_download_bytes'],
                total_connect_count=stats['total_connect_count'],
                ip_count=ip_count,
            )
        )
    
    return result


@router.get("/user/devices/{device_id}", response_model=UserDeviceResponse)
def user_get_device_details(
    db: DBDep,
    user: UserDep,
    device_id: int = Path(...),
):
    """
    Get details about a specific device (user's own).
    """
    device = device_crud.get_device_by_id(db, device_id)
    if not device or device.user_id != user.id:
        raise HTTPException(status_code=404, detail="Device not found")
    
    # Get statistics
    stats = device_crud.get_device_total_traffic(db, device.id)
    ips = device_crud.get_device_ips(db, device.id)
    
    # Get last IP (without detailed geo info for users)
    last_ip = None
    if device.last_ip_id:
        last_ip_obj = device_crud.get_device_ip_by_id(db, device.last_ip_id)
        if last_ip_obj:
            last_ip = DeviceIP.model_validate(last_ip_obj)
    
    return UserDeviceResponse(
        **device.__dict__,
        last_ip=last_ip,
        total_upload_bytes=stats['total_upload_bytes'],
        total_download_bytes=stats['total_download_bytes'],
        total_connect_count=stats['total_connect_count'],
        ips=[DeviceIP.model_validate(ip) for ip in ips],
    )


@router.patch("/user/devices/{device_id}", response_model=UserDeviceResponse)
def user_update_device(
    db: DBDep,
    user: UserDep,
    modifications: UserDeviceModify,
    device_id: int = Path(...),
):
    """
    Update device settings (user's own).
    Users can only change display_name.
    """
    device = device_crud.get_device_by_id(db, device_id)
    if not device or device.user_id != user.id:
        raise HTTPException(status_code=404, detail="Device not found")
    
    # Users can only modify display_name
    updated_device = device_crud.update_device(
        db=db,
        device_id=device_id,
        display_name=modifications.display_name,
    )
    
    if not updated_device:
        raise HTTPException(status_code=500, detail="Failed to update device")
    
    # Get full response
    stats = device_crud.get_device_total_traffic(db, device.id)
    ips = device_crud.get_device_ips(db, device.id)
    
    last_ip = None
    if updated_device.last_ip_id:
        last_ip_obj = device_crud.get_device_ip_by_id(db, updated_device.last_ip_id)
        if last_ip_obj:
            last_ip = DeviceIP.model_validate(last_ip_obj)
    
    return UserDeviceResponse(
        **updated_device.__dict__,
        last_ip=last_ip,
        total_upload_bytes=stats['total_upload_bytes'],
        total_download_bytes=stats['total_download_bytes'],
        total_connect_count=stats['total_connect_count'],
        ips=[DeviceIP.model_validate(ip) for ip in ips],
    )


@router.delete("/user/devices/{device_id}", status_code=204)
def user_block_device(
    db: DBDep,
    user: UserDep,
    device_id: int = Path(...),
):
    """
    Block a device (user's own).
    Sets is_blocked=True instead of deleting.
    """
    device = device_crud.get_device_by_id(db, device_id)
    if not device or device.user_id != user.id:
        raise HTTPException(status_code=404, detail="Device not found")
    
    # Block instead of delete
    device_crud.update_device(db, device_id, is_blocked=True)
    
    return None

