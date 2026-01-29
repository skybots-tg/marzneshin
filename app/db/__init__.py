import logging
from sqlalchemy.exc import SQLAlchemyError, TimeoutError as SATimeoutError
from sqlalchemy.orm import Session

from .base import Base, SessionLocal, engine  # noqa
from .crud import (
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
from .models import JWT, System, User, UserDevice, UserDeviceIP, UserDeviceTraffic  # noqa
from . import device_crud  # noqa

logger = logging.getLogger(__name__)


class GetDB:  # Context Manager
    """
    Context manager for database sessions with improved error handling.
    
    Features:
    - Automatic rollback on exceptions
    - Connection pool timeout handling
    - Proper session cleanup
    """
    
    def __init__(self):
        self.db = None

    def __enter__(self):
        try:
            self.db = SessionLocal()
            return self.db
        except SATimeoutError:
            logger.error("Database connection pool timeout - all connections are busy")
            raise
        except SQLAlchemyError as e:
            logger.error(f"Database connection error: {e}")
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
                    logger.warning(f"Rolling back due to database error: {exc_value}")
        except Exception as rollback_error:
            logger.error(f"Error during rollback: {rollback_error}")
        finally:
            try:
                self.db.close()
            except Exception as close_error:
                logger.error(f"Error closing database session: {close_error}")


__all__ = [
    "get_user",
    "get_user_by_id",
    "get_users",
    "get_users_count",
    "create_user",
    "remove_user",
    "update_user",
    "update_user_status",
    "update_user_sub",
    "revoke_user_sub",
    "set_owner",
    "get_system_usage",
    "get_jwt_secret_key",
    "get_tls_certificate",
    "get_admin",
    "create_admin",
    "update_admin",
    "remove_admin",
    "get_admins",
    "GetDB",
    "User",
    "System",
    "JWT",
    "UserDevice",
    "UserDeviceIP",
    "UserDeviceTraffic",
    "device_crud",
    "Base",
    "Session",
]
