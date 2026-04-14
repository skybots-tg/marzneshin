import logging
import time

from app.config.env import NODE_UNHEALTHY_ALERT_COOLDOWN, TELEGRAM_ADMIN_ID
from app.notification.telegram import send_message

logger = logging.getLogger(__name__)

_unhealthy_cooldowns: dict[int, float] = {}


def _build_admin_tags() -> str:
    """Build HTML mention links for all configured admin IDs."""
    if not TELEGRAM_ADMIN_ID:
        return ""
    tags = " ".join(
        f'<a href="tg://user?id={uid}">admin</a>' for uid in TELEGRAM_ADMIN_ID
    )
    return f"\n{tags}"


async def notify_node_unhealthy(
    node_id: int,
    address: str,
    error_message: str | None = None,
) -> None:
    """Send an urgent Telegram alert when a node becomes unhealthy.

    Respects a per-node cooldown so admins aren't spammed when a node
    flaps or retries frequently.
    """
    now = time.monotonic()
    last_notified = _unhealthy_cooldowns.get(node_id, 0)
    if now - last_notified < NODE_UNHEALTHY_ALERT_COOLDOWN:
        return

    _unhealthy_cooldowns[node_id] = now

    error_detail = f"\n<b>Error:</b> <code>{error_message}</code>" if error_message else ""
    text = (
        f"🚨 <b>СРОЧНО — #NodeUnhealthy</b>\n"
        f"➖➖➖➖➖➖➖➖➖\n"
        f"<b>Node ID:</b> <code>{node_id}</code>\n"
        f"<b>Address:</b> <code>{address}</code>"
        f"{error_detail}\n"
        f"➖➖➖➖➖➖➖➖➖"
        f"{_build_admin_tags()}"
    )

    try:
        await send_message(text)
    except Exception:
        logger.exception("Failed to send node-unhealthy alert for node %d", node_id)
