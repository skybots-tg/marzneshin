from typing import List

from sqlalchemy.orm import Session, selectinload

from app.db.models import Service, Inbound
from app.models.service import Service as ServiceModify, ServiceCreate


def create_service(db: Session, service: ServiceCreate) -> Service:
    dbservice = Service(
        name=service.name,
        inbounds=db.query(Inbound)
        .filter(Inbound.id.in_(service.inbound_ids))
        .all(),
        users=[],
    )
    db.add(dbservice)
    db.commit()
    db.refresh(dbservice)
    return dbservice


def get_service(db: Session, service_id: id) -> Service:
    return (
        db.query(Service)
        .options(
            selectinload(Service.inbounds),
            selectinload(Service.users),
        )
        .filter(Service.id == service_id)
        .first()
    )


def get_services(db: Session) -> List[Service]:
    return db.query(Service).all()


def update_service(
    db: Session, db_service: Service, modification: ServiceModify
):
    if modification.name is not None:
        db_service.name = modification.name

    if modification.inbound_ids is not None:
        db_service.inbounds = (
            db.query(Inbound)
            .filter(Inbound.id.in_(modification.inbound_ids))
            .all()
        )

    db.commit()
    db.refresh(db_service)
    return db_service


def remove_service(db: Session, db_service: Service):
    db.delete(db_service)
    db.commit()
    return db_service
