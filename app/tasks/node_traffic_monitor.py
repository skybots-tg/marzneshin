"""Alert when a node goes quiet at an hour it is normally busy.

Runs periodically alongside record_user_usages, tracking when each registered
node last reported non-zero traffic. The gap alone is not the alarm, and
treating it as one is what made this alert unreadable: ten minutes of silence
is an outage at eight in the evening and the most ordinary thing in the world
at four in the morning, so a fixed threshold fired every night on nodes that
were perfectly fine. Two questions are asked before the gap is believed at all.

*Can this node carry traffic?* A node whose every host is hidden moves nothing
by construction — the audit hid them — and complaining about its silence is
the loop that kept TR and NL-2 out of the catalogue for days while sending
forty messages each per day about it.

*Is this hour normally busy for it?* The node's own traffic during this clock
hour on each of the past days answers that (``node_traffic_profile``). Below
the floor there, silence is the norm and nothing is said.

What is left is a node that has subscribers, normally moves real traffic at
this time of day, and has stopped. That is worth a message.
"""

import logging
import time

from app.marznode.database import node_name as registered_node_name
from app.marznode.registry import node_registry
from app.utils.node_traffic_profile import (
    BASELINE_FLOOR_BYTES_PER_HOUR,
    expected_now,
    nodes_with_visible_hosts,
)

logger = logging.getLogger(__name__)

TRAFFIC_SILENCE_THRESHOLD = 600  # seconds (10 min) without traffic → alert
TRAFFIC_ALERT_COOLDOWN = 1800  # seconds (30 min) between repeated alerts
# The profile moves once an hour; the check runs every two minutes. Re-reading
# it every tick would be two pointless queries a minute against node_usages.
PROFILE_TTL = 300  # seconds

_last_traffic_ts: dict[int, float] = {}
_last_alert_ts: dict[int, float] = {}
_profile: tuple[float, dict[int, float], set[int]] | None = None


def _context() -> tuple[dict[int, float], set[int]]:
    """(expected bytes this hour per node, nodes with a visible host)."""
    global _profile
    now = time.monotonic()
    if _profile is None or now - _profile[0] > PROFILE_TTL:
        _profile = (now, expected_now(), nodes_with_visible_hosts())
    return _profile[1], _profile[2]


def record_node_activity(node_id: int, had_traffic: bool) -> None:
    """Called from record_user_usages after collecting stats for a node."""
    if had_traffic:
        _last_traffic_ts[node_id] = time.monotonic()


async def check_node_traffic_silence() -> None:
    """Check all registered nodes for traffic silence and alert."""
    now = time.monotonic()
    registered_ids = node_registry.list_ids()
    usual, reachable = _context()

    for node_id in registered_ids:
        last_seen = _last_traffic_ts.get(node_id)

        if last_seen is None:
            if node_id not in _last_traffic_ts:
                _last_traffic_ts[node_id] = now
            continue

        silence_seconds = now - last_seen

        if silence_seconds < TRAFFIC_SILENCE_THRESHOLD:
            continue

        if node_id not in reachable:
            continue  # every host hidden: it cannot be carrying anything

        expected = usual.get(node_id, 0.0)
        if expected < BASELINE_FLOOR_BYTES_PER_HOUR:
            continue  # this hour is normally quiet for this node

        last_alert = _last_alert_ts.get(node_id, 0)
        if now - last_alert < TRAFFIC_ALERT_COOLDOWN:
            continue

        _last_alert_ts[node_id] = now

        node = node_registry.get(node_id)
        address = getattr(node, "_address", "unknown") if node else "unknown"
        name = registered_node_name(node_id)

        silence_min = int(silence_seconds / 60)
        logger.warning(
            "Node %d (%s %s): no traffic for %d minutes, "
            "this hour usually carries %.1f MB",
            node_id, name or "?", address, silence_min, expected / (1 << 20),
        )

        await notify_node_traffic_silence(
            node_id=node_id,
            address=address,
            silence_minutes=silence_min,
            node_name=name,
            expected_mb=expected / (1 << 20),
        )

    stale = set(_last_traffic_ts.keys()) - set(registered_ids)
    for nid in stale:
        _last_traffic_ts.pop(nid, None)
        _last_alert_ts.pop(nid, None)


async def notify_node_traffic_silence(
    node_id: int,
    address: str,
    silence_minutes: int,
    node_name: str | None = None,
    expected_mb: float = 0.0,
) -> None:
    """Send Telegram alert about traffic silence on a node."""
    from app.config.env import TELEGRAM_ADMIN_ID
    from app.notification.node_alerts import build_node_lines
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
        f"{build_node_lines(node_id, address, node_name)}\n"
        f"<b>Молчит:</b> {silence_minutes} мин\n"
        f"<b>Обычно в этот час:</b> {expected_mb:.0f} МБ\n"
        f"➖➖➖➖➖➖➖➖➖\n"
        f"Сравнение с этим же часом прошлых дней, а не с фиксированным "
        f"порогом: узлы, которые ночью молчат всегда, сюда не попадают.\n"
        f"Возможные причины:\n"
        f"• Marznode упал или завис\n"
        f"• gRPC-соединение разорвано\n"
        f"• Xray-процесс на ноде не работает\n"
        f"• Сломался фронт маскировки (dest не отвечает)"
        f"{admin_tags}"
    )

    try:
        await send_message(text)
    except Exception:
        logger.exception(
            "Failed to send traffic-silence alert for node %d", node_id
        )
