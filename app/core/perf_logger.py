"""Conditional performance logger.

Writes to a dedicated log file ONLY when anomalies occur:
- Slow HTTP responses (> threshold)
- DB connection pool pressure (high utilization)
- DB connection pool exhaustion (timeout waiting for connection)
- Slow SQL queries

Captures server load context (CPU, memory, pool stats) alongside each event
so that we can correlate slowdowns with resource pressure.
"""

import logging
import os
import time
from logging.handlers import RotatingFileHandler

try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    psutil = None  # type: ignore[assignment]
    _HAS_PSUTIL = False

_PERF_LOG_PATH = os.environ.get(
    "MARZNESHIN_PERF_LOG", "/var/lib/marzneshin/perf.log"
)
_SLOW_REQUEST_THRESHOLD = float(os.environ.get("PERF_SLOW_REQUEST_SEC", "2.0"))
_SLOW_QUERY_THRESHOLD = float(os.environ.get("PERF_SLOW_QUERY_SEC", "1.0"))
_POOL_WARN_PERCENT = int(os.environ.get("PERF_POOL_WARN_PCT", "70"))

perf_logger = logging.getLogger("marzneshin.perf")
perf_logger.setLevel(logging.DEBUG)
perf_logger.propagate = False

try:
    _handler = RotatingFileHandler(
        _PERF_LOG_PATH, maxBytes=10 * 1024 * 1024, backupCount=3
    )
except (PermissionError, FileNotFoundError):
    _handler = logging.StreamHandler()

_handler.setFormatter(
    logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
)
perf_logger.addHandler(_handler)


def _get_pool_stats():
    """Lazy import to avoid circular dependency with app.db.base."""
    try:
        from app.db.base import get_pool_stats
        return get_pool_stats()
    except Exception:
        return None


def _server_context() -> str:
    """Snapshot of CPU / memory / pool for log lines."""
    try:
        pool = _get_pool_stats()
        if pool is None:
            raise ValueError
        pool_str = (
            f"pool_out={pool['checked_out']}/{pool['max_connections']} "
            f"pool_overflow={pool['overflow']}"
        )
    except Exception:
        pool_str = "pool=unavailable"

    if _HAS_PSUTIL:
        try:
            cpu = psutil.cpu_percent(interval=0)
            mem = psutil.virtual_memory()
            return f"cpu={cpu:.0f}% mem_used={mem.percent:.0f}% {pool_str}"
        except Exception:
            pass

    load_str = ""
    if hasattr(os, "getloadavg"):
        try:
            la = os.getloadavg()
            load_str = f"load1m={la[0]:.1f} "
        except Exception:
            pass
    return f"{load_str}{pool_str}"


def log_slow_request(
    method: str, path: str, status: int, duration_sec: float,
    *, extra: str = "",
):
    if duration_sec < _SLOW_REQUEST_THRESHOLD:
        return
    ctx = _server_context()
    perf_logger.warning(
        "SLOW_REQUEST | %s %s -> %d | %.2fs | %s%s",
        method, path, status, duration_sec, ctx,
        f" | {extra}" if extra else "",
    )


def log_slow_query(statement: str, duration_sec: float, *, engine_name: str = "main"):
    if duration_sec < _SLOW_QUERY_THRESHOLD:
        return
    ctx = _server_context()
    stmt_preview = (statement[:200] + "...") if len(statement) > 200 else statement
    perf_logger.warning(
        "SLOW_QUERY | engine=%s | %.2fs | %s | %s",
        engine_name, duration_sec, stmt_preview.replace("\n", " "), ctx,
    )


def log_pool_pressure(event: str, checked_out: int, max_conn: int, **kw):
    """Called when pool utilization crosses thresholds or checkout times out."""
    ctx = _server_context()
    extras = " ".join(f"{k}={v}" for k, v in kw.items())
    perf_logger.error(
        "POOL_PRESSURE | %s | out=%d/%d | %s | %s",
        event, checked_out, max_conn, extras, ctx,
    )


def log_task_duration(task_name: str, duration_sec: float, *, details: str = ""):
    """Log background task timing when it takes suspiciously long."""
    threshold = 5.0
    if duration_sec < threshold:
        return
    ctx = _server_context()
    perf_logger.warning(
        "SLOW_TASK | %s | %.2fs | %s%s",
        task_name, duration_sec, ctx,
        f" | {details}" if details else "",
    )


# --- Convenience: config accessors for other modules ---
SLOW_REQUEST_THRESHOLD = _SLOW_REQUEST_THRESHOLD
SLOW_QUERY_THRESHOLD = _SLOW_QUERY_THRESHOLD
POOL_WARN_PERCENT = _POOL_WARN_PERCENT
