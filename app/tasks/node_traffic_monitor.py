"""Monitor node traffic flow and alert when a node stops reporting data.

Runs periodically alongside record_user_usages. Tracks the last time
each registered node reported non-zero traffic. If the gap exceeds
a configurable threshold, fires a Telegram alert (with per-node cooldown).
"""

import logging
import time
from datetime import datetime

from app.marznode.registry import node_registry
from app.notification.node_alerts import notify_node_unhealthy

logger = logging.getLogger(__name__)

TRAFFIC_SILENCE_THRESHOLD = 600  # seconds (10 min) without traffic → alert
TRAFFIC_ALERT_COOLDOWN = 1800  # seconds (30 min) between repeated alerts

_last_traffic_ts: dict[int, float] = {}
_last_alert_ts: dict[int, float] = {}


def record_node_activity(node_id: int, had_traffic: bool) -> None:
    """Called from record_user_usages after collecting stats for a node."""
    if had_traffic:
        _last_traffic_ts[node_id] = time.monotonic()


async def check_node_traffic_silence() -> None:
    """Check all registered nodes for traffic silence and alert."""
    now = time.monotonic()
    registered_ids = node_registry.list_ids()

    for node_id in registered_ids:
        last_seen = _last_traffic_ts.get(node_id)

        if last_seen is None:
            if node_id not in _last_traffic_ts:
                _last_traffic_ts[node_id] = now
            continue

        silence_seconds = now - last_seen

        if silence_seconds < TRAFFIC_SILENCE_THRESHOLD:
            continue

        last_alert = _last_alert_ts.get(node_id, 0)
        if now - last_alert < TRAFFIC_ALERT_COOLDOWN:
            continue

        _last_alert_ts[node_id] = now

        node = node_registry.get(node_id)
        address = getattr(node, "_address", "unknown") if node else "unknown"

        silence_min = int(silence_seconds / 60)
        logger.warning(
            "Node %d (%s): no traffic for %d minutes",
            node_id, address, silence_min,
        )

        await notify_node_traffic_silence(
            node_id=node_id,
            address=address,
            silence_minutes=silence_min,
        )

    stale = set(_last_traffic_ts.keys()) - set(registered_ids)
    for nid in stale:
        _last_traffic_ts.pop(nid, None)
        _last_alert_ts.pop(nid, None)


async def notify_node_traffic_silence(
    node_id: int,
    address: str,
    silence_minutes: int,
) -> None:
    """Send Telegram alert about traffic silence on a node."""
    from app.config.env import TELEGRAM_ADMIN_ID
    from app.notification.telegram import send_message

    admin_tags = ""
    if TELEGRAM_ADMIN_ID:
        tags = " ".join(
            f'<a href="tg://user?id={uid}">admin</a>'
            for uid in TELEGRAM_ADMIN_ID
        )
        admin_tags = f"\n{tags}"

    text = (
        f"⚠️ <b>#TrafficSilence — нет трафика</b>\n"
        f"➖➖➖➖➖➖➖➖➖\n"
        f"<b>Node ID:</b> <code>{node_id}</code>\n"
        f"<b>Address:</b> <code>{address}</code>\n"
        f"<b>Молчит:</b> {silence_minutes} мин\n"
        f"➖➖➖➖➖➖➖➖➖\n"
        f"Возможные причины:\n"
        f"• Marznode упал или завис\n"
        f"• gRPC-соединение разорвано\n"
        f"• Xray-процесс на ноде не работает\n"
        f"• Нет активных пользователей"
        f"{admin_tags}"
    )

    try:
        await send_message(text)
    except Exception:
        logger.exception(
            "Failed to send traffic-silence alert for node %d", node_id
        )
