import logging
import threading
import time

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

_LONG_CHECKOUT_WARN = 15  # seconds — warn when a connection is held this long

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


def _get_max_connections(pool):
    """Return the maximum number of connections the pool can hold.

    Returns None when overflow is unlimited (-1).
    """
    max_overflow = getattr(pool, "_max_overflow", 0)
    if max_overflow < 0:
        return None
    return pool.size() + max_overflow


def _attach_pool_diagnostics(eng, name: str):
    """Attach checkout/checkin event listeners for pool pressure diagnostics."""

    @event.listens_for(eng, "checkout")
    def _on_checkout(dbapi_conn, conn_record, conn_proxy):
        conn_record.info["_checkout_at"] = time.monotonic()
        pool = eng.pool
        max_conn = _get_max_connections(pool)
        if not max_conn:
            return
        checked = pool.checkedout()
        utilization = checked / max_conn
        if utilization >= 0.8:
            logger.warning(
                "[%s] Pool high utilization on checkout: %d/%d (%.0f%%), overflow=%d",
                name, checked, max_conn, utilization * 100, max(0, pool.overflow()),
            )

    @event.listens_for(eng, "checkin")
    def _on_checkin(dbapi_conn, conn_record):
        start = conn_record.info.pop("_checkout_at", None)
        if start is None:
            return
        held = time.monotonic() - start
        if held > _LONG_CHECKOUT_WARN:
            logger.warning(
                "[%s] Connection returned after %.1fs (threshold %ds)",
                name, held, _LONG_CHECKOUT_WARN,
            )


def _create_engine(pool_size, max_overflow, pool_timeout, pool_recycle,
                   *, name: str = "unknown"):
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
                cursor.execute("SET SESSION max_statement_time = %s", (int(SQLALCHEMY_STATEMENT_TIMEOUT),))
            else:
                cursor.execute("SET SESSION max_execution_time = %s", (int(SQLALCHEMY_STATEMENT_TIMEOUT * 1000),))
            cursor.close()

    if not IS_SQLITE:
        _attach_pool_diagnostics(eng, name)

    return eng


class EnginePool:
    """Unified engine pool with stats, reconfiguration, and thread safety."""

    def __init__(self, name: str, pool_size: int, max_overflow: int,
                 pool_timeout: int, pool_recycle: int):
        self.name = name
        self._lock = threading.Lock()
        self._engine = _create_engine(
            pool_size, max_overflow, pool_timeout, pool_recycle,
            name=name,
        )
        self.session_factory = sessionmaker(
            autocommit=False, autoflush=False, bind=self._engine,
        )
        logger.info(
            "[%s] Pool created: pool_size=%d, max_overflow=%d",
            name, pool_size, max_overflow,
        )

    @property
    def engine(self):
        with self._lock:
            return self._engine

    def get_stats(self) -> dict:
        """Return live pool statistics."""
        with self._lock:
            pool = self._engine.pool
        raw_overflow = pool.overflow()
        max_conn = _get_max_connections(pool)
        return {
            "name": self.name,
            "pool_size": pool.size(),
            "max_overflow": getattr(pool, "_max_overflow", 0),
            "checked_out": pool.checkedout(),
            "checked_in": pool.checkedin(),
            "overflow": max(0, raw_overflow),
            "pool_timeout": SQLALCHEMY_POOL_TIMEOUT,
            "pool_recycle": SQLALCHEMY_POOL_RECYCLE,
            "statement_timeout": SQLALCHEMY_STATEMENT_TIMEOUT,
            "connect_timeout": SQLALCHEMY_CONNECT_TIMEOUT,
            "total_connections": pool.checkedout() + pool.checkedin(),
            "max_connections": max_conn or -1,
        }

    def reconfigure(self, pool_size: int, max_overflow: int,
                    pool_timeout: int, pool_recycle: int):
        """Recreate the engine with new pool parameters (thread-safe)."""
        with self._lock:
            old = self._engine
            self._engine = _create_engine(
                pool_size, max_overflow, pool_timeout, pool_recycle,
                name=self.name,
            )
            self.session_factory.configure(bind=self._engine)
            old.dispose(close=False)
            logger.info(
                "[%s] Pool reconfigured: pool_size=%d, max_overflow=%d, "
                "pool_timeout=%d, pool_recycle=%d",
                self.name, pool_size, max_overflow, pool_timeout, pool_recycle,
            )


# --- Pool instances ---
main_pool = EnginePool(
    "main",
    SQLALCHEMY_CONNECTION_POOL_SIZE,
    SQLALCHEMY_CONNECTION_MAX_OVERFLOW,
    SQLALCHEMY_POOL_TIMEOUT,
    SQLALCHEMY_POOL_RECYCLE,
)

settings_pool = EnginePool(
    "settings",
    _SETTINGS_POOL_SIZE,
    _SETTINGS_MAX_OVERFLOW,
    SQLALCHEMY_POOL_TIMEOUT,
    SQLALCHEMY_POOL_RECYCLE,
)

# --- Backward-compatible aliases ---
engine = main_pool.engine
SessionLocal = main_pool.session_factory
settings_engine = settings_pool.engine
SettingsSessionLocal = settings_pool.session_factory

Base = declarative_base()


def get_pool_stats():
    """Return live pool statistics for the main engine."""
    return main_pool.get_stats()


def reconfigure_pool(pool_size: int, max_overflow: int,
                     pool_timeout: int, pool_recycle: int):
    """Recreate the main engine with new pool parameters (thread-safe)."""
    global engine
    main_pool.reconfigure(pool_size, max_overflow, pool_timeout, pool_recycle)
    engine = main_pool.engine
