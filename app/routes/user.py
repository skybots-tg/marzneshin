import logging
from enum import StrEnum

from fastapi import APIRouter, Query
from fastapi_pagination.ext.sqlalchemy import paginate
from fastapi_pagination.links import Page
from sqlalchemy.orm import selectinload, load_only

from app.db import crud
from app.db.models import Service, Inbound
from app.db.models.core import User
from app.dependencies import (
    DBDep,
    AdminDep,
    SudoAdminDep,
    UserDep,
    StartDateDep,
    EndDateDep,
    ModifyUsersAccess,
)
from app.models.service import ServiceResponse
from app.models.user import (
    UserCreate,
    UserModify,
    UserResponse,
    UserUsageSeriesResponse,
)
from app.services import user_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/users", tags=["User"])


class UsersSortingOptions(StrEnum):
    USERNAME = "username"
    USED_TRAFFIC = "used_traffic"
    DATA_LIMIT = "data_limit"
    EXPIRE_DATE = "expire_date"
    CREATED_AT = "created_at"


@router.get("", response_model=Page[UserResponse])
def get_users(
    db: DBDep,
    admin: AdminDep,
    username: list[str] = Query(None),
    order_by: UsersSortingOptions = Query(None),
    descending: bool = Query(False),
    is_active: bool | None = Query(None),
    activated: bool | None = Query(None),
    expired: bool | None = Query(None),
    data_limit_reached: bool | None = Query(None),
    enabled: bool | None = Query(None),
    owner_username: str | None = Query(None),
):
    dbadmin = crud.get_admin(db, admin.username)
    query = db.query(User).filter(User.removed == False)  # noqa: E712
    owner_admin = dbadmin if not admin.is_sudo else None

    if username is not None:
        if len(username) > 1:
            query = query.filter(User.username.in_(username))
        else:
            query = query.filter(User.username.ilike(f"%{username[0]}%"))

    if owner_username is not None:
        if not dbadmin.is_sudo:
            from fastapi import HTTPException

            raise HTTPException(403, "You're not allowed.")
        filter_admin = crud.get_admin(db, owner_username)
        if not filter_admin:
            from fastapi import HTTPException

            raise HTTPException(404, "owner_username not found.")
        query = query.filter(User.admin_id == filter_admin.id)

    if is_active is not None:
        query = query.filter(User.is_active == is_active)
    if activated is not None:
        query = query.filter(User.activated == activated)
    if expired is not None:
        query = query.filter(User.expired == expired)
    if data_limit_reached is not None:
        query = query.filter(User.data_limit_reached == data_limit_reached)
    if enabled is not None:
        query = query.filter(User.enabled == enabled)

    if owner_admin:
        query = query.filter(User.admin == owner_admin)

    if order_by:
        order_column = getattr(User, order_by)
        if descending:
            order_column = order_column.desc()
        query = query.order_by(order_column)

    return paginate(db, query)


@router.post("", response_model=UserResponse)
def add_user(new_user: UserCreate, db: DBDep, admin: AdminDep):
    db_user = user_service.create_user(db, new_user, admin)
    return UserResponse.model_validate(db_user)


@router.post("/reset")
def reset_users_data_usage(db: DBDep, admin: SudoAdminDep):
    dbadmin = crud.get_admin(db, admin.username)
    crud.reset_all_users_data_usage(db=db, admin=dbadmin)
    return {}


@router.delete("/expired")
def delete_expired(
    passed_time: int,
    db: DBDep,
    admin: AdminDep,
    modify_access: ModifyUsersAccess,
):
    user_service.delete_expired_users(db, passed_time, admin)
    return {}


@router.get("/{username}", response_model=UserResponse)
def get_user(db_user: UserDep):
    return db_user


@router.put("/{username}", response_model=UserResponse)
def modify_user(
    db_user: UserDep,
    modifications: UserModify,
    db: DBDep,
    admin: AdminDep,
    modify_access: ModifyUsersAccess,
):
    return user_service.modify_user(db, db_user, modifications, admin)


@router.delete("/{username}")
def remove_user(
    db_user: UserDep,
    db: DBDep,
    admin: AdminDep,
    modify_access: ModifyUsersAccess,
):
    user_service.remove_user(db, db_user, admin)
    return {}


@router.get("/{username}/services", response_model=Page[ServiceResponse])
def get_user_services(user: UserDep, db: DBDep, admin: AdminDep):
    query = (
        db.query(Service)
        .options(
            selectinload(Service.inbounds).load_only(Inbound.id),
            selectinload(Service.users).load_only(User.id, User.removed),
        )
        .join(Service.users)
        .where(User.username == user.username)
    )
    if not admin.is_sudo and not admin.all_services_access:
        query = query.filter(Service.id.in_(admin.service_ids))
    return paginate(query)


@router.post("/{username}/reset", response_model=UserResponse)
def reset_user_data_usage(
    db_user: UserDep,
    db: DBDep,
    admin: AdminDep,
    modify_access: ModifyUsersAccess,
):
    return user_service.reset_data_usage(db, db_user, admin)


@router.post("/{username}/enable", response_model=UserResponse)
def enable_user(
    db_user: UserDep,
    db: DBDep,
    admin: AdminDep,
    modify_access: ModifyUsersAccess,
):
    return user_service.enable_user(db, db_user, admin)


@router.post("/{username}/disable", response_model=UserResponse)
def disable_user(
    db_user: UserDep,
    db: DBDep,
    admin: AdminDep,
    modify_access: ModifyUsersAccess,
):
    return user_service.disable_user(db, db_user, admin)


@router.post("/{username}/revoke_sub", response_model=UserResponse)
def revoke_user_subscription(
    db_user: UserDep,
    db: DBDep,
    admin: AdminDep,
    modify_access: ModifyUsersAccess,
):
    return user_service.revoke_subscription(db, db_user, admin)


@router.get("/{username}/usage", response_model=UserUsageSeriesResponse)
def get_user_usage(
    db: DBDep, db_user: UserDep, start_date: StartDateDep, end_date: EndDateDep
):
    return crud.get_user_usages(db, db_user, start_date, end_date)


@router.put("/{username}/set-owner", response_model=UserResponse)
def set_owner(
    username: str, admin_username: str, db: DBDep, admin: SudoAdminDep
):
    from fastapi import HTTPException

    db_user = crud.get_user(db, username)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    new_admin = crud.get_admin(db, username=admin_username)
    if not new_admin:
        raise HTTPException(status_code=404, detail="Admin not found")

    db_user = crud.set_owner(db, db_user, new_admin)
    logger.info(
        "`%s`'s owner successfully set to `%s`",
        db_user.username,
        admin_username,
    )
    return UserResponse.model_validate(db_user)
