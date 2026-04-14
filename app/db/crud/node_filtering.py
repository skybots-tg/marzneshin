from sqlalchemy.orm import Session

from app.db.models.node_filtering import (
    NodeFilteringConfig,
    NodeSSHCredentials,
)
from app.models.node_filtering import NodeFilteringConfigUpdate


def get_filtering_config(db: Session, node_id: int) -> NodeFilteringConfig | None:
    return (
        db.query(NodeFilteringConfig)
        .filter(NodeFilteringConfig.node_id == node_id)
        .first()
    )


def get_or_create_filtering_config(db: Session, node_id: int) -> NodeFilteringConfig:
    cfg = get_filtering_config(db, node_id)
    if cfg is None:
        cfg = NodeFilteringConfig(node_id=node_id)
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    return cfg


def update_filtering_config(
    db: Session, node_id: int, update: NodeFilteringConfigUpdate
) -> NodeFilteringConfig:
    cfg = get_or_create_filtering_config(db, node_id)
    for field, value in update.model_dump(exclude_unset=True).items():
        setattr(cfg, field, value)
    db.commit()
    db.refresh(cfg)
    return cfg


def set_adguard_installed(db: Session, node_id: int, installed: bool) -> None:
    cfg = get_or_create_filtering_config(db, node_id)
    cfg.adguard_home_installed = installed
    db.commit()


def get_ssh_credentials(db: Session, node_id: int) -> NodeSSHCredentials | None:
    return (
        db.query(NodeSSHCredentials)
        .filter(NodeSSHCredentials.node_id == node_id)
        .first()
    )


def save_ssh_credentials(
    db: Session,
    node_id: int,
    encrypted_data: str,
    encryption_salt: str,
) -> NodeSSHCredentials:
    creds = get_ssh_credentials(db, node_id)
    if creds is None:
        creds = NodeSSHCredentials(
            node_id=node_id,
            encrypted_data=encrypted_data,
            encryption_salt=encryption_salt,
        )
        db.add(creds)
    else:
        creds.encrypted_data = encrypted_data
        creds.encryption_salt = encryption_salt
    db.commit()
    db.refresh(creds)
    return creds


def has_any_ssh_credentials(db: Session) -> bool:
    return db.query(NodeSSHCredentials).first() is not None


def delete_all_ssh_credentials(db: Session) -> int:
    count = db.query(NodeSSHCredentials).delete()
    db.commit()
    return count


def delete_ssh_credentials(db: Session, node_id: int) -> bool:
    creds = get_ssh_credentials(db, node_id)
    if creds is None:
        return False
    db.delete(creds)
    db.commit()
    return True
