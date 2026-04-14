"""Database package.

Provides session management via ``GetDB`` / ``GetSettingsDB`` context managers
and re-exports commonly used symbols for backward compatibility.
"""

import logging

from sqlalchemy.exc import SQLAlchemyError, TimeoutError as SATimeoutError
from sqlalchemy.orm import Session  # noqa: F401

from .base import Base, SessionLocal, SettingsSessionLocal, engine  # noqa: F401
from .base import get_pool_stats, reconfigure_pool  # noqa: F401
from . import device_crud  # noqa: F401

logger = logging.getLogger(__name__)


class GetDB:
    """Context manager for database sessions."""

    def __init__(self):
        self.db = None

    def __enter__(self):
        try:
            self.db = SessionLocal()
            return self.db
        except SATimeoutError:
            logger.error(
                "Database connection pool timeout - all connections are busy"
            )
            raise
        except SQLAlchemyError as e:
            logger.error("Database connection error: %s", e)
            raise

    def __exit__(self, exc_type, exc_value, traceback):
        if self.db is None:
            return

        try:
            if exc_value is not None:
                self.db.rollback()
                if isinstance(exc_value, SATimeoutError):
                    logger.warning("Rolling back due to database timeout")
                elif isinstance(exc_value, SQLAlchemyError):
                    logger.warning(
                        "Rolling back due to database error: %s", exc_value
                    )
        except Exception as rollback_error:
            logger.error("Error during rollback: %s", rollback_error)
        finally:
            try:
                self.db.close()
            except Exception as close_error:
                logger.error(
                    "Error closing database session: %s", close_error
                )


class GetSettingsDB:
    """Context manager using the dedicated settings engine."""

    def __init__(self):
        self.db = None

    def __enter__(self):
        try:
            self.db = SettingsSessionLocal()
            return self.db
        except SATimeoutError:
            logger.error("Settings DB pool timeout")
            raise
        except SQLAlchemyError as e:
            logger.error("Settings DB connection error: %s", e)
            raise

    def __exit__(self, exc_type, exc_value, traceback):
        if self.db is None:
            return
        try:
            if exc_value is not None:
                self.db.rollback()
        except Exception:
            pass
        finally:
            try:
                self.db.close()
            except Exception:
                pass


# Backward-compatible re-exports — new code should import directly from
# ``app.db.crud`` and ``app.db.models``.
from .crud import (  # noqa: E402,F401
    create_admin,
    create_user,
    get_admin,
    get_admins,
    get_jwt_secret_key,
    ensure_node_inbounds,
    get_system_usage,
    get_tls_certificate,
    get_user,
    get_user_by_id,
    get_users,
    get_users_count,
    remove_admin,
    remove_user,
    revoke_user_sub,
    set_owner,
    update_admin,
    update_user,
    update_user_status,
    update_user_sub,
)
from .models import (  # noqa: E402,F401
    JWT,
    System,
    User,
    UserDevice,
    UserDeviceIP,
    UserDeviceTraffic,
)
