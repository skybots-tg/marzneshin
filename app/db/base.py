import logging
import threading

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker

from app.config.env import (
    SQLALCHEMY_DATABASE_URL,
    SQLALCHEMY_CONNECTION_POOL_SIZE,
    SQLALCHEMY_CONNECTION_MAX_OVERFLOW,
    SQLALCHEMY_POOL_TIMEOUT,
    SQLALCHEMY_POOL_RECYCLE,
    SQLALCHEMY_STATEMENT_TIMEOUT,
    SQLALCHEMY_CONNECT_TIMEOUT,
)

logger = logging.getLogger(__name__)

IS_SQLITE = SQLALCHEMY_DATABASE_URL.startswith("sqlite")
IS_MYSQL = SQLALCHEMY_DATABASE_URL.startswith("mysql") or SQLALCHEMY_DATABASE_URL.startswith("mariadb")
IS_MARIADB = SQLALCHEMY_DATABASE_URL.startswith("mariadb")
IS_POSTGRES = SQLALCHEMY_DATABASE_URL.startswith("postgresql")

_SETTINGS_POOL_SIZE = 2
_SETTINGS_MAX_OVERFLOW = 1

logger.info(
    f"Database config: url={SQLALCHEMY_DATABASE_URL.split('@')[-1] if '@' in SQLALCHEMY_DATABASE_URL else SQLALCHEMY_DATABASE_URL}, "
    f"pool_size={SQLALCHEMY_CONNECTION_POOL_SIZE}, max_overflow={SQLALCHEMY_CONNECTION_MAX_OVERFLOW}, "
    f"pool_timeout={SQLALCHEMY_POOL_TIMEOUT}, pool_recycle={SQLALCHEMY_POOL_RECYCLE}"
)


def _build_connect_args():
    """Build connect_args dict based on database type."""
    if IS_SQLITE:
        return {"check_same_thread": False, "timeout": SQLALCHEMY_STATEMENT_TIMEOUT}
    elif IS_MYSQL:
        return {
            "connect_timeout": SQLALCHEMY_CONNECT_TIMEOUT,
            "read_timeout": SQLALCHEMY_STATEMENT_TIMEOUT,
            "write_timeout": SQLALCHEMY_STATEMENT_TIMEOUT,
        }
    elif IS_POSTGRES:
        return {
            "connect_timeout": SQLALCHEMY_CONNECT_TIMEOUT,
            "options": f"-c statement_timeout={SQLALCHEMY_STATEMENT_TIMEOUT * 1000}",
        }
    return {}


def _create_engine(pool_size, max_overflow, pool_timeout, pool_recycle):
    """Create a SQLAlchemy engine with given pool parameters."""
    kwargs = dict(
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_recycle=pool_recycle,
        pool_timeout=pool_timeout,
    )
    connect_args = _build_connect_args()
    if connect_args:
        kwargs["connect_args"] = connect_args
    if not IS_SQLITE:
        kwargs["pool_pre_ping"] = True

    eng = create_engine(SQLALCHEMY_DATABASE_URL, **kwargs)

    if IS_MYSQL:
        @event.listens_for(eng, "connect")
        def _set_mysql_timeout(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            if IS_MARIADB:
                cursor.execute(f"SET SESSION max_statement_time = {SQLALCHEMY_STATEMENT_TIMEOUT}")
            else:
                cursor.execute(f"SET SESSION max_execution_time = {SQLALCHEMY_STATEMENT_TIMEOUT * 1000}")
            cursor.close()

    return eng


# --- Main engine (used by the entire application) ---
engine = _create_engine(
    SQLALCHEMY_CONNECTION_POOL_SIZE,
    SQLALCHEMY_CONNECTION_MAX_OVERFLOW,
    SQLALCHEMY_POOL_TIMEOUT,
    SQLALCHEMY_POOL_RECYCLE,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# --- Settings engine (dedicated small pool, always accessible) ---
settings_engine = _create_engine(
    _SETTINGS_POOL_SIZE, _SETTINGS_MAX_OVERFLOW,
    SQLALCHEMY_POOL_TIMEOUT, SQLALCHEMY_POOL_RECYCLE,
)
SettingsSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=settings_engine)

Base = declarative_base()

# Lock for thread-safe engine  reconfiguration
_engine_lock = threading.Lock()


def get_pool_stats():
    """Return live pool statistics for the main engine."""
    pool = engine.pool
    # pool.overflow() can be negative (means pool hasn't filled to base size yet);
    # clamp to 0 for a user-friendly display.
    raw_overflow = pool.overflow()
    return {
        "pool_size": pool.size(),
        "max_overflow": engine.pool._max_overflow,
        "checked_out": pool.checkedout(),
        "checked_in": pool.checkedin(),
        "overflow": max(0, raw_overflow),
        "pool_timeout": SQLALCHEMY_POOL_TIMEOUT,
        "pool_recycle": SQLALCHEMY_POOL_RECYCLE,
        "statement_timeout": SQLALCHEMY_STATEMENT_TIMEOUT,
        "connect_timeout": SQLALCHEMY_CONNECT_TIMEOUT,
        "total_connections": pool.checkedout() + pool.checkedin(),
        "max_connections": pool.size() + engine.pool._max_overflow,
    }


def reconfigure_pool(pool_size: int, max_overflow: int,
                     pool_timeout: int, pool_recycle: int):
    """Recreate the main engine with new pool parameters (thread-safe)."""
    global engine, SessionLocal

    with _engine_lock:
        old_engine = engine
        engine = _create_engine(pool_size, max_overflow, pool_timeout, pool_recycle)
        SessionLocal.configure(bind=engine)
        old_engine.dispose()
        logger.info(
            f"Pool reconfigured: pool_size={pool_size}, max_overflow={max_overflow}, "
            f"pool_timeout={pool_timeout}, pool_recycle={pool_recycle}"
        )
