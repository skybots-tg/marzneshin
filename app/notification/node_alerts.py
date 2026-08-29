import logging
import time

from app.config.env import NODE_UNHEALTHY_ALERT_COOLDOWN, TELEGRAM_ADMIN_ID
from app.notification.telegram import send_message
from app.utils.node_country import country_label

logger = logging.getLogger(__name__)

_unhealthy_cooldowns: dict[int, float] = {}


def build_node_lines(node_id: int, address: str, node_name: str | None) -> str:
    """The "which node is this" block every node alert opens with.

    An id and an IP name the node without saying anything about it. The country
    is what decides whether an alert is worth getting out of bed for, and it is
    already written in the node's own name — see ``app.utils.node_country``.
    """
    lines = [
        f"<b>Node ID:</b> <code>{node_id}</code>",
        f"<b>Нода:</b> {node_name}" if node_name else None,
        f"<b>Страна:</b> {country_label(node_name)}",
        f"<b>Address:</b> <code>{address}</code>",
    ]
    return "\n".join(line for line in lines if line)


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
    node_name: str | None = None,
) -> None:
    """Send an urgent Telegram alert when a node becomes unhealthy.

    Respects a per-node cooldown so admins aren't spammed when a node
    flaps or retries frequently. Skips alerts for nodes that are no
    longer registered (operator disabled or removed them) — otherwise
    in-flight error handlers in the monitor loop would keep spamming
    after the node was turned off.
    """
    from app.marznode.registry import node_registry

    if node_id not in node_registry:
        return

    now = time.monotonic()
    last_notified = _unhealthy_cooldowns.get(node_id, 0)
    if now - last_notified < NODE_UNHEALTHY_ALERT_COOLDOWN:
        return

    _unhealthy_cooldowns[node_id] = now

    error_detail = f"\n<b>Error:</b> <code>{error_message}</code>" if error_message else ""
    text = (
        f"🚨 <b>СРОЧНО — #NodeUnhealthy</b>\n"
        f"➖➖➖➖➖➖➖➖➖\n"
        f"{build_node_lines(node_id, address, node_name)}"
        f"{error_detail}\n"
        f"➖➖➖➖➖➖➖➖➖"
        f"{_build_admin_tags()}"
    )

    try:
        await send_message(text)
    except Exception:
        logger.exception("Failed to send node-unhealthy alert for node %d", node_id)
