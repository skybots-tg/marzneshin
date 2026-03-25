import time

from sqlalchemy.orm import Session

from app.db.models import JWT, TLS, System

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
    return db.query(JWT).first().secret_key


def get_tls_certificate(db: Session):
    return db.query(TLS).first()
