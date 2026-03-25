import logging
import time

from app.config.env import TELEGRAM_ADMIN_ID
from app.db.base import get_pool_stats

logger = logging.getLogger(__name__)

_last_warn_time: float = 0
_last_crit_time: float = 0
_WARN_COOLDOWN = 300   # 5 min between WARNING alerts
_CRIT_COOLDOWN = 60    # 1 min between CRITICAL alerts — gives faster feedback
_POOL_WARN_PERCENT = 70
_POOL_CRIT_PERCENT = 90


def _build_admin_mentions() -> str:
    if not TELEGRAM_ADMIN_ID:
        return ""
    return " ".join(
        f'<a href="tg://user?id={uid}">Admin</a>'
        for uid in TELEGRAM_ADMIN_ID
    )


def _get_node_db_info() -> str:
    """Best-effort fetch of node-DB throttle stats."""
    try:
        from app.marznode.database import get_node_db_pressure
        info = get_node_db_pressure()
        return (
            f"<b>Node DB throttle:</b> "
            f"<code>waiting={info['waiting']}, max={info['max_concurrent']}</code>"
        )
    except Exception:
        return ""


async def check_pool_health():
    """Periodic check of DB connection pool; sends Telegram alert when pressure is high."""
    global _last_warn_time, _last_crit_time

    try:
        stats = get_pool_stats()
    except Exception as e:
        logger.error("Failed to get pool stats: %s", e)
        return

    checked_out = stats["checked_out"]
    max_connections = stats["max_connections"]
    if max_connections == 0:
        return

    utilization = (checked_out / max_connections) * 100

    if utilization >= 50:
        logger.info(
            "Pool utilization %.0f%%: checked_out=%d, checked_in=%d, overflow=%d, max=%d",
            utilization, checked_out, stats["checked_in"],
            stats["overflow"], max_connections,
        )

    if utilization < _POOL_WARN_PERCENT:
        return

    now = time.time()
    is_critical = utilization >= _POOL_CRIT_PERCENT

    if is_critical:
        if (now - _last_crit_time) < _CRIT_COOLDOWN:
            return
        _last_crit_time = now
    else:
        if (now - _last_warn_time) < _WARN_COOLDOWN:
            return
        _last_warn_time = now

    level = "\U0001f534 CRITICAL" if is_critical else "\U0001f7e1 WARNING"
    mentions = _build_admin_mentions()
    node_info = _get_node_db_info()

    message = (
        f"{level} <b>#PoolAlert</b>\n"
        f"➖➖➖➖➖➖➖➖➖\n"
        f"<b>DB Connection Pool под нагрузкой!</b>\n\n"
        f"<b>Active (checked out):</b> <code>{checked_out}/{max_connections}</code>"
        f" ({utilization:.0f}%)\n"
        f"<b>Idle (checked in):</b> <code>{stats['checked_in']}</code>\n"
        f"<b>Overflow:</b> <code>{stats['overflow']}/{stats['max_overflow']}</code>\n"
        f"<b>Total connections:</b> <code>{stats['total_connections']}/{max_connections}</code>\n"
    )
    if node_info:
        message += f"{node_info}\n"
    message += (
        f"➖➖➖➖➖➖➖➖➖\n"
        f"{mentions}"
    )

    try:
        from app.notification.telegram import send_message
        await send_message(message)
    except Exception as e:
        logger.error("Failed to send pool alert: %s", e)

    logger.warning(
        "Pool alert sent: %d/%d connections active (%.0f%%)",
        checked_out, max_connections, utilization,
    )
