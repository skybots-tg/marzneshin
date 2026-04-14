import time

from sqlalchemy.orm import Session

from app.db.models import JWT, TLS, System, Settings

_subscription_settings_cache = {"data": None, "expires": 0}


def get_subscription_settings_cached(db: Session):
    """Get subscription settings with caching (60s TTL)."""
    from app.db.models import Settings

    now = time.time()
    if _subscription_settings_cache["data"] is not None and now < _subscription_settings_cache["expires"]:
        return _subscription_settings_cache["data"]

    result = db.query(Settings.subscription).first()
    if result:
        _subscription_settings_cache["data"] = result[0]
        _subscription_settings_cache["expires"] = now + 60
        return result[0]
    return None


def invalidate_subscription_settings_cache():
    """Call this when settings are updated."""
    _subscription_settings_cache["data"] = None
    _subscription_settings_cache["expires"] = 0


def get_system_usage(db: Session):
    return db.query(System).first()


def get_jwt_secret_key(db: Session):
    row = db.query(JWT).first()
    if not row:
        raise RuntimeError("JWT secret key not found in database. Run migrations first.")
    return row.secret_key


def get_tls_certificate(db: Session):
    return db.query(TLS).first()


def get_ssh_pin_hash(db: Session) -> str | None:
    row = db.query(Settings.ssh_pin_hash).first()
    return row[0] if row else None


def set_ssh_pin_hash(db: Session, pin_hash: str) -> None:
    settings = db.query(Settings).first()
    if not settings:
        raise RuntimeError("Settings row not found")
    settings.ssh_pin_hash = pin_hash
    db.commit()


def clear_ssh_pin_hash(db: Session) -> None:
    settings = db.query(Settings).first()
    if not settings:
        raise RuntimeError("Settings row not found")
    settings.ssh_pin_hash = None
    db.commit()
