"""Database package.

Provides session management via ``GetDB`` / ``GetSettingsDB`` context managers
and re-exports commonly used symbols for backward compatibility.
"""

import logging

from sqlalchemy.exc import SQLAlchemyError, TimeoutError as SATimeoutError
from sqlalchemy.orm import Session  # noqa: F401

from .base import Base, SessionLocal, SettingsSessionLocal, engine  # noqa: F401
from .base import main_pool, settings_pool  # noqa: F401
from .base import get_pool_stats, reconfigure_pool  # noqa: F401
from . import device_crud  # noqa: F401

logger = logging.getLogger(__name__)


class _DBSession:
    """Unified context manager for database sessions."""

    def __init__(self, pool_name: str, session_factory):
        self._pool_name = pool_name
        self._session_factory = session_factory
        self.db = None

    def __enter__(self):
        try:
            self.db = self._session_factory()
            return self.db
        except SATimeoutError:
            logger.error(
                "[%s] Connection pool timeout - all connections are busy",
                self._pool_name,
            )
            raise
        except SQLAlchemyError as e:
            logger.error("[%s] Connection error: %s", self._pool_name, e)
            raise

    def __exit__(self, exc_type, exc_value, traceback):
        if self.db is None:
            return
        try:
            if exc_value is not None:
                self.db.rollback()
                if isinstance(exc_value, SATimeoutError):
                    logger.warning(
                        "[%s] Rolling back due to database timeout",
                        self._pool_name,
                    )
                elif isinstance(exc_value, SQLAlchemyError):
                    logger.warning(
                        "[%s] Rolling back due to database error: %s",
                        self._pool_name, exc_value,
                    )
        except Exception as rollback_error:
            logger.error(
                "[%s] Error during rollback: %s",
                self._pool_name, rollback_error,
            )
        finally:
            try:
                self.db.close()
            except Exception as close_error:
                logger.error(
                    "[%s] Error closing session: %s",
                    self._pool_name, close_error,
                )


class GetDB(_DBSession):
    """Context manager for main database sessions."""

    def __init__(self):
        super().__init__("main", SessionLocal)


class GetSettingsDB(_DBSession):
    """Context manager for settings database sessions."""

    def __init__(self):
        super().__init__("settings", SettingsSessionLocal)


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
