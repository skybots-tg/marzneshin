import logging

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
IS_MYSQL = SQLALCHEMY_DATABASE_URL.startswith("mysql")
IS_POSTGRES = SQLALCHEMY_DATABASE_URL.startswith("postgresql")

logger.info(
    f"Database config: url={SQLALCHEMY_DATABASE_URL.split('@')[-1] if '@' in SQLALCHEMY_DATABASE_URL else SQLALCHEMY_DATABASE_URL}, "
    f"pool_size={SQLALCHEMY_CONNECTION_POOL_SIZE}, max_overflow={SQLALCHEMY_CONNECTION_MAX_OVERFLOW}, "
    f"pool_timeout={SQLALCHEMY_POOL_TIMEOUT}, pool_recycle={SQLALCHEMY_POOL_RECYCLE}"
)

if IS_SQLITE:
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        pool_size=SQLALCHEMY_CONNECTION_POOL_SIZE,
        max_overflow=SQLALCHEMY_CONNECTION_MAX_OVERFLOW,
        pool_recycle=SQLALCHEMY_POOL_RECYCLE,
        pool_timeout=SQLALCHEMY_POOL_TIMEOUT,
        connect_args={"check_same_thread": False, "timeout": SQLALCHEMY_STATEMENT_TIMEOUT},
    )
elif IS_MYSQL:
    # MySQL connection args for timeouts
    connect_args = {
        "connect_timeout": SQLALCHEMY_CONNECT_TIMEOUT,
        "read_timeout": SQLALCHEMY_STATEMENT_TIMEOUT,
        "write_timeout": SQLALCHEMY_STATEMENT_TIMEOUT,
    }
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        pool_size=SQLALCHEMY_CONNECTION_POOL_SIZE,
        max_overflow=SQLALCHEMY_CONNECTION_MAX_OVERFLOW,
        pool_recycle=SQLALCHEMY_POOL_RECYCLE,
        pool_timeout=SQLALCHEMY_POOL_TIMEOUT,
        pool_pre_ping=True,
        connect_args=connect_args,
    )
elif IS_POSTGRES:
    # PostgreSQL connection args for timeouts
    connect_args = {
        "connect_timeout": SQLALCHEMY_CONNECT_TIMEOUT,
        "options": f"-c statement_timeout={SQLALCHEMY_STATEMENT_TIMEOUT * 1000}",  # in milliseconds
    }
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        pool_size=SQLALCHEMY_CONNECTION_POOL_SIZE,
        max_overflow=SQLALCHEMY_CONNECTION_MAX_OVERFLOW,
        pool_recycle=SQLALCHEMY_POOL_RECYCLE,
        pool_timeout=SQLALCHEMY_POOL_TIMEOUT,
        pool_pre_ping=True,
        connect_args=connect_args,
    )
else:
    # Generic database configuration
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        pool_size=SQLALCHEMY_CONNECTION_POOL_SIZE,
        max_overflow=SQLALCHEMY_CONNECTION_MAX_OVERFLOW,
        pool_recycle=SQLALCHEMY_POOL_RECYCLE,
        pool_timeout=SQLALCHEMY_POOL_TIMEOUT,
        pool_pre_ping=True,
    )


# Set statement timeout for MariaDB on each connection checkout
if IS_MYSQL:
    @event.listens_for(engine, "connect")
    def set_mysql_timeout(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute(f"SET SESSION max_execution_time = {SQLALCHEMY_STATEMENT_TIMEOUT * 1000}")
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
