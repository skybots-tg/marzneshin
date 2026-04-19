from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models.node_tls import NodeTLSProvisioning


def get_tls_provisioning(
    db: Session, node_id: int
) -> NodeTLSProvisioning | None:
    return (
        db.query(NodeTLSProvisioning)
        .filter(NodeTLSProvisioning.node_id == node_id)
        .first()
    )


def upsert_tls_provisioning(
    db: Session,
    node_id: int,
    *,
    domain: str,
    landing_template: str,
    grpc_service_name: str,
    uds_path: str,
    contact_email: str,
) -> NodeTLSProvisioning:
    row = get_tls_provisioning(db, node_id)
    if row is None:
        row = NodeTLSProvisioning(
            node_id=node_id,
            domain=domain,
            landing_template=landing_template,
            grpc_service_name=grpc_service_name,
            uds_path=uds_path,
            contact_email=contact_email,
        )
        db.add(row)
    else:
        row.domain = domain
        row.landing_template = landing_template
        row.grpc_service_name = grpc_service_name
        row.uds_path = uds_path
        row.contact_email = contact_email
    db.commit()
    db.refresh(row)
    return row


def update_cert_dates(
    db: Session,
    node_id: int,
    *,
    issued_at: datetime | None,
    expires_at: datetime | None,
) -> NodeTLSProvisioning | None:
    row = get_tls_provisioning(db, node_id)
    if row is None:
        return None
    row.cert_issued_at = issued_at
    row.cert_expires_at = expires_at
    row.last_renew_attempt_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return row


def mark_renew_attempted(db: Session, node_id: int) -> None:
    row = get_tls_provisioning(db, node_id)
    if row is None:
        return
    row.last_renew_attempt_at = datetime.utcnow()
    db.commit()


def delete_tls_provisioning(db: Session, node_id: int) -> bool:
    row = get_tls_provisioning(db, node_id)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True
