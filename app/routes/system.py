from fastapi import APIRouter, HTTPException

from app.db import crud, get_pool_stats, reconfigure_pool
from app.db.crud.system import invalidate_subscription_settings_cache
from app.db.models import Admin as DBAdmin, Settings
from app.db.models import Node
from app.dependencies import (
    DBDep,
    SettingsDBDep,
    AdminDep,
    SudoAdminDep,
    EndDateDep,
    StartDateDep,
)
from app.models.node import NodeStatus
from app.models.settings import (
    SubscriptionSettings,
    TelegramSettings,
    DatabasePoolConfig,
    DatabasePoolStats,
    SSHPinStatus,
    SSHPinSetup,
)
from app.models.system import (
    UsersStats,
    NodesStats,
    AdminsStats,
    TrafficUsageSeries,
)
from app.models.user import UserExpireStrategy

router = APIRouter(tags=["System"], prefix="/system")


@router.get("/settings/subscription", response_model=SubscriptionSettings)
def get_subscription_settings(db: DBDep, admin: SudoAdminDep):
    result = db.query(Settings.subscription).first()
    if not result:
        raise HTTPException(status_code=404, detail="Settings not found")
    return result[0]


@router.put("/settings/subscription", response_model=SubscriptionSettings)
def update_subscription_settings(
    db: DBDep, modifications: SubscriptionSettings, admin: SudoAdminDep
):
    settings = db.query(Settings).first()
    if not settings:
        raise HTTPException(status_code=404, detail="Settings not found")
    settings.subscription = modifications.model_dump(mode="json")
    db.commit()
    invalidate_subscription_settings_cache()
    return settings.subscription


@router.get("/settings/telegram", response_model=TelegramSettings | None)
def get_telegram_settings(db: DBDep, admin: SudoAdminDep):
    result = db.query(Settings).first()
    if not result:
        raise HTTPException(status_code=404, detail="Settings not found")
    return result.telegram


@router.put("/settings/telegram", response_model=TelegramSettings | None)
def update_telegram_settings(
    db: DBDep, new_telegram: TelegramSettings | None, admin: SudoAdminDep
):
    settings = db.query(Settings).first()
    if not settings:
        raise HTTPException(status_code=404, detail="Settings not found")
    settings.telegram = new_telegram
    db.commit()
    return settings.telegram


@router.get("/settings/database", response_model=DatabasePoolStats)
def get_database_pool_settings(
    db: SettingsDBDep, admin: SudoAdminDep
):
    """Get current database pool configuration and live stats.
    Uses a separate dedicated connection pool so this endpoint
    remains accessible even when the main pool is exhausted."""
    return get_pool_stats()


@router.put("/settings/database", response_model=DatabasePoolStats)
def update_database_pool_settings(
    db: SettingsDBDep,
    config: DatabasePoolConfig,
    admin: SudoAdminDep,
):
    """Apply new pool parameters at runtime by recreating the main engine.
    The settings engine (used by this endpoint) is not affected."""
    reconfigure_pool(
        pool_size=config.pool_size,
        max_overflow=config.max_overflow,
        pool_timeout=config.pool_timeout,
        pool_recycle=config.pool_recycle,
    )
    return get_pool_stats()


@router.get("/settings/ssh-pin", response_model=SSHPinStatus)
def get_ssh_pin_status(db: DBDep, admin: SudoAdminDep):
    pin_hash = crud.get_ssh_pin_hash(db)
    has_creds = crud.has_any_ssh_credentials(db)
    return SSHPinStatus(configured=pin_hash is not None, has_credentials=has_creds)


@router.post("/settings/ssh-pin", response_model=SSHPinStatus)
def setup_ssh_pin(db: DBDep, body: SSHPinSetup, admin: SudoAdminDep):
    from app.utils.crypto import hash_pin

    existing = crud.get_ssh_pin_hash(db)
    if existing is not None:
        raise HTTPException(409, "PIN is already configured. Delete it first.")

    crud.set_ssh_pin_hash(db, hash_pin(body.pin))
    return SSHPinStatus(configured=True, has_credentials=False)


@router.delete("/settings/ssh-pin", response_model=SSHPinStatus)
def delete_ssh_pin(db: DBDep, admin: SudoAdminDep):
    existing = crud.get_ssh_pin_hash(db)
    if existing is None:
        raise HTTPException(404, "PIN is not configured")

    if crud.has_any_ssh_credentials(db):
        raise HTTPException(
            409,
            "Cannot delete PIN while SSH credentials exist. "
            "Delete all stored SSH credentials first.",
        )

    crud.clear_ssh_pin_hash(db)
    return SSHPinStatus(configured=False, has_credentials=False)


@router.get("/stats/admins", response_model=AdminsStats)
def get_admins_stats(db: DBDep, admin: SudoAdminDep):
    return AdminsStats(total=db.query(DBAdmin).count())


@router.get("/stats/nodes", response_model=NodesStats)
def get_nodes_stats(db: DBDep, admin: SudoAdminDep):
    return NodesStats(
        total=db.query(Node).count(),
        healthy=db.query(Node)
        .filter(Node.status == NodeStatus.healthy)
        .count(),
        unhealthy=db.query(Node)
        .filter(Node.status == NodeStatus.unhealthy)
        .count(),
    )


@router.get("/stats/traffic", response_model=TrafficUsageSeries)
def get_total_traffic_stats(
    db: DBDep, admin: AdminDep, start_date: StartDateDep, end_date: EndDateDep
):
    return crud.get_total_usages(db, admin, start_date, end_date)


@router.get("/stats/users", response_model=UsersStats)
def get_users_stats(db: DBDep, admin: AdminDep):
    return UsersStats(
        total=crud.get_users_count(
            db, admin=admin if not admin.is_sudo else None
        ),
        active=crud.get_users_count(
            db, admin=admin if not admin.is_sudo else None, is_active=True
        ),
        on_hold=crud.get_users_count(
            db,
            admin=admin if not admin.is_sudo else None,
            expire_strategy=UserExpireStrategy.START_ON_FIRST_USE,
        ),
        expired=crud.get_users_count(
            db,
            admin=admin if not admin.is_sudo else None,
            expired=True,
        ),
        limited=crud.get_users_count(
            db,
            admin=admin if not admin.is_sudo else None,
            data_limit_reached=True,
        ),
        online=crud.get_users_count(
            db, admin=admin if not admin.is_sudo else None, online=True
        ),
    )
