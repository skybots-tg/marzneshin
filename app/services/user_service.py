import asyncio
import logging
from datetime import datetime, timedelta

import sqlalchemy
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db import crud
from app.db.models import User
from app.models.admin import Admin
from app.models.notification import UserNotification
from app.models.user import UserCreate, UserModify, UserResponse
from app.marznode import operations as node_ops
from app.notification.notifiers import notify

logger = logging.getLogger(__name__)


def _allowed_services(admin: Admin) -> list | None:
    if admin.is_sudo or admin.all_services_access:
        return None
    return admin.service_ids


def create_user(db: Session, new_user: UserCreate, admin: Admin) -> User:
    try:
        db_user = crud.create_user(
            db,
            new_user,
            admin=crud.get_admin(db, admin.username),
            allowed_services=_allowed_services(admin),
        )
    except sqlalchemy.exc.IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="User already exists")

    node_ops.update_user(user=db_user, db=db)

    asyncio.ensure_future(
        notify(
            action=UserNotification.Action.user_created,
            user=UserResponse.model_validate(db_user),
            by=admin,
        )
    )
    logger.info("New user `%s` added", db_user.username)
    return db_user


def modify_user(
    db: Session, db_user: User, modifications: UserModify, admin: Admin
) -> User:
    active_before = db_user.is_active
    old_inbounds = {(i.node_id, i.protocol, i.tag) for i in db_user.inbounds}

    new_user = crud.update_user(
        db, db_user, modifications,
        allowed_services=_allowed_services(admin),
    )

    active_after = new_user.is_active
    new_inbounds = {(i.node_id, i.protocol, i.tag) for i in new_user.inbounds}
    inbound_change = old_inbounds != new_inbounds

    if (inbound_change and new_user.is_active) or active_before != active_after:
        node_ops.update_user(
            new_user, old_inbounds, remove=not db_user.is_active, db=db
        )
        db_user.activated = db_user.is_active
        db.commit()

    asyncio.ensure_future(
        notify(
            action=UserNotification.Action.user_updated,
            user=UserResponse.model_validate(db_user),
            by=admin,
        )
    )
    logger.info("User `%s` modified", db_user.username)

    if active_before != active_after:
        action = (
            UserNotification.Action.user_activated
            if active_after
            else UserNotification.Action.user_deactivated
        )
        asyncio.ensure_future(
            notify(
                action=action,
                user=UserResponse.model_validate(db_user),
                by=admin,
            )
        )
        logger.info(
            "User `%s` activation changed from `%s` to `%s`",
            db_user.username, active_before, active_after,
        )

    return db_user


def remove_user(db: Session, db_user: User, admin: Admin) -> UserResponse:
    node_ops.update_user(db_user, remove=True, db=db)

    deleted_username = db_user.username
    crud.remove_user(db, db_user)

    db_user.username = deleted_username
    user = UserResponse.model_validate(db_user)
    db.expunge(db_user)

    asyncio.ensure_future(
        notify(
            action=UserNotification.Action.user_deleted, user=user, by=admin
        )
    )
    logger.info("User %s deleted", db_user.username)
    return user


def delete_expired_users(
    db: Session, passed_time: int, admin: Admin
) -> None:
    dbadmin = crud.get_admin(db, admin.username)

    db_users = crud.get_users(
        db=db,
        expired=True,
        admin=dbadmin if not admin.is_sudo else None,
    )

    current_time = datetime.utcnow()
    expiration_threshold = current_time - timedelta(seconds=passed_time)
    expired_users = [
        user
        for user in db_users
        if user.expire_date is not None
        and user.expire_date <= expiration_threshold
    ]
    if not expired_users:
        raise HTTPException(status_code=404, detail="No expired user found.")

    for db_user in expired_users:
        crud.remove_user(db, db_user)
        logger.info("User `%s` removed", db_user.username)


def reset_data_usage(db: Session, db_user: User, admin: Admin) -> User:
    was_active = db_user.is_active
    db_user = crud.reset_user_data_usage(db, db_user)

    if db_user.is_active and not was_active:
        node_ops.update_user(db_user, db=db)
        db_user.activated = True
        db.commit()

    asyncio.ensure_future(
        notify(
            action=UserNotification.Action.data_usage_reset,
            user=UserResponse.model_validate(db_user),
            by=admin,
        )
    )
    logger.info("User `%s`'s usage was reset", db_user.username)
    return db_user


def enable_user(db: Session, db_user: User, admin: Admin) -> User:
    if db_user.enabled:
        raise HTTPException(409, "User is already enabled")

    db_user.enabled = True
    if db_user.is_active:
        db_user.activated = True
        node_ops.update_user(db_user, db=db)
    db.commit()

    asyncio.ensure_future(
        notify(
            action=UserNotification.Action.user_enabled,
            user=UserResponse.model_validate(db_user),
            by=admin,
        )
    )
    logger.info("User `%s` has been enabled", db_user.username)
    return db_user


def disable_user(db: Session, db_user: User, admin: Admin) -> User:
    if not db_user.enabled:
        raise HTTPException(409, "User is not enabled")

    db_user.enabled = False
    db_user.activated = False
    db.commit()
    node_ops.update_user(db_user, remove=True, db=db)

    asyncio.ensure_future(
        notify(
            action=UserNotification.Action.user_disabled,
            user=UserResponse.model_validate(db_user),
            by=admin,
        )
    )
    logger.info("User `%s` has been disabled", db_user.username)
    return db_user


def revoke_subscription(db: Session, db_user: User, admin: Admin) -> User:
    db_user = crud.revoke_user_sub(db, db_user)

    if db_user.is_active:
        node_ops.update_user(db_user, remove=True, db=db)
        node_ops.update_user(db_user, db=db)

    asyncio.ensure_future(
        notify(
            action=UserNotification.Action.subscription_revoked,
            user=UserResponse.model_validate(db_user),
            by=admin,
        )
    )
    logger.info("User %s subscription revoked", db_user.username)
    return db_user
