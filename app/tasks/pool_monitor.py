import logging
import time

from app.config.env import TELEGRAM_ADMIN_ID
from app.db.base import get_pool_stats

logger = logging.getLogger(__name__)

_last_alert_time: float = 0
_ALERT_COOLDOWN = 300  # seconds between repeated alerts
_POOL_WARN_PERCENT = 70
_POOL_CRIT_PERCENT = 90


def _build_admin_mentions() -> str:
    if not TELEGRAM_ADMIN_ID:
        return ""
    return " ".join(
        f'<a href="tg://user?id={uid}">Admin</a>'
        for uid in TELEGRAM_ADMIN_ID
    )


async def check_pool_health():
    """Periodic check of DB connection pool; sends Telegram alert when pressure is high."""
    global _last_alert_time

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
    if utilization < _POOL_WARN_PERCENT:
        return

    now = time.time()
    if (now - _last_alert_time) < _ALERT_COOLDOWN:
        return
    _last_alert_time = now

    level = (
        "\U0001f534 CRITICAL" if utilization >= _POOL_CRIT_PERCENT
        else "\U0001f7e1 WARNING"
    )
    mentions = _build_admin_mentions()

    message = (
        f"{level} <b>#PoolAlert</b>\n"
        f"➖➖➖➖➖➖➖➖➖\n"
        f"<b>DB Connection Pool под нагрузкой!</b>\n\n"
        f"<b>Active (checked out):</b> <code>{checked_out}/{max_connections}</code>"
        f" ({utilization:.0f}%)\n"
        f"<b>Idle (checked in):</b> <code>{stats['checked_in']}</code>\n"
        f"<b>Overflow:</b> <code>{stats['overflow']}/{stats['max_overflow']}</code>\n"
        f"<b>Total connections:</b> <code>{stats['total_connections']}/{max_connections}</code>\n"
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
