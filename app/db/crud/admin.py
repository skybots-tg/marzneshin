from datetime import datetime
from types import NoneType
from typing import Optional

from sqlalchemy.orm import Session

from app.db.models import Admin, Service
from app.models.admin import AdminCreate, AdminPartialModify


def get_admin(db: Session, username: str) -> Admin | None:
    return db.query(Admin).filter(Admin.username == username).first()


def create_admin(db: Session, admin: AdminCreate):
    dbadmin = Admin(
        username=admin.username,
        hashed_password=admin.hashed_password,
        is_sudo=admin.is_sudo,
        enabled=admin.enabled,
        all_services_access=admin.all_services_access,
        modify_users_access=admin.modify_users_access,
        services=db.query(Service)
        .filter(Service.id.in_(admin.service_ids))
        .all(),
        subscription_url_prefix=admin.subscription_url_prefix,
    )
    db.add(dbadmin)
    db.commit()
    db.refresh(dbadmin)
    return dbadmin


def update_admin(
    db: Session, dbadmin: Admin, modifications: AdminPartialModify
):
    for attribute in [
        "is_sudo",
        "hashed_password",
        "enabled",
        "all_services_access",
        "modify_users_access",
        "subscription_url_prefix",
    ]:
        if not isinstance(getattr(modifications, attribute), NoneType):
            setattr(dbadmin, attribute, getattr(modifications, attribute))
            if attribute == "hashed_password":
                dbadmin.password_reset_at = datetime.utcnow()
    if isinstance(modifications.service_ids, list):
        dbadmin.services = (
            db.query(Service)
            .filter(Service.id.in_(modifications.service_ids))
            .all()
        )
    db.commit()
    db.refresh(dbadmin)
    return dbadmin


def partial_update_admin(
    db: Session, dbadmin: Admin, modified_admin: AdminPartialModify
):
    if modified_admin.is_sudo is not None:
        dbadmin.is_sudo = modified_admin.is_sudo
    if (
        modified_admin.password is not None
        and dbadmin.hashed_password != modified_admin.hashed_password
    ):
        dbadmin.hashed_password = modified_admin.hashed_password
        dbadmin.password_reset_at = datetime.utcnow()

    db.commit()
    db.refresh(dbadmin)
    return dbadmin


def remove_admin(db: Session, dbadmin: Admin):
    db.delete(dbadmin)
    db.commit()
    return dbadmin


def get_admins(
    db: Session,
    offset: Optional[int] = None,
    limit: Optional[int] = None,
    username: Optional[str] = None,
):
    query = db.query(Admin)
    if username:
        query = query.filter(Admin.username.ilike(f"%{username}%"))
    if offset:
        query = query.offset(offset)
    if limit:
        query = query.limit(limit)
    return query.all()
