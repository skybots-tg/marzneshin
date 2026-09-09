"""Alert when an exit keeps working by every check and stops carrying traffic.

This is the failure the rest of the monitoring cannot see. France went from
200 GB a day to zero and stayed there for three days while the node answered
SSH, ran marznode with 434 users, held its listener port open, kept its reality
keys in sync with the panel and reported ``healthy`` throughout. Its masking
front — ``www.free.fr`` — had quietly stopped negotiating TLS 1.3, and REALITY
serves the client a handshake borrowed from ``dest``, so a dead ``dest`` refuses
every subscriber under every ``serverName`` while looking perfect from the
outside. Nothing in the fleet was watching the one number that changed.

So this watches that number, and it watches it the only way that does not cry
wolf: a node against itself, at the same hours of the day, over the past week
(``node_traffic_profile``). A quiet night is quiet in the baseline too.

Deliberately conservative, because a false alarm here is expensive — it points
at a working server:

* only nodes that carry real traffic in that week are eligible at all;
* only nodes a subscriber can still reach — an exit whose hosts the audit has
  hidden has no traffic to lose, and saying so twice helps nobody;
* the collapse has to survive two consecutive checks, so a deploy restarting
  xray for a minute does not count;
* and recovery is reported, so a thread that started with an alarm ends.
"""

import logging
import time

from app.marznode.database import node_name as registered_node_name
from app.marznode.registry import node_registry
from app.utils.node_traffic_profile import (
    nodes_with_visible_hosts,
    traffic_vs_baseline,
)

logger = logging.getLogger(__name__)

# A fiftieth of normal — "the traffic is gone", not "the traffic is down".
# A tenth sounded right and was not: measured against a real evening, six nodes
# crossed it at once, and only two of them had anything wrong. Catalogue
# changes move traffic between entries by factors of ten all the time; a slot
# that broke goes to a rounding error. France sat at 0.01% for three days.
COLLAPSE_RATIO = 0.02
# Back above this and the node is called recovered. The gap is deliberate: a
# node hovering at the threshold should not alternate between two messages
# every half hour.
RECOVERY_RATIO = 0.2
# Everything is judged relative to how the fleet as a whole is doing right now.
# Without it, one broken exit drags every entry that fed it below the threshold
# and the alarm reports the blast radius instead of the fault — which is
# exactly what happened when France went: four entries lost their traffic and
# not one of them was broken.
FLEET_FLOOR = 0.05
CONFIRMATIONS = 2       # consecutive checks before the first message
ALERT_COOLDOWN = 6 * 3600

_streak: dict[int, int] = {}
_alerted: dict[int, float] = {}


async def check_node_traffic_collapse() -> None:
    readings = traffic_vs_baseline(recent_hours=2, baseline_days=7)
    if not readings:
        return
    reachable = nodes_with_visible_hosts()
    registered = set(node_registry.list_ids())
    now = time.monotonic()
    fleet = _fleet_ratio(readings)

    for node_id, reading in readings.items():
        if node_id not in registered or node_id not in reachable:
            _streak.pop(node_id, None)
            continue
        if not reading.meaningful:
            _streak.pop(node_id, None)
            continue

        # Against the fleet, not against yesterday: a quiet night, a holiday
        # or an outage somewhere else moves everyone at once.
        ratio = reading.ratio / fleet
        if ratio >= RECOVERY_RATIO:
            _streak.pop(node_id, None)
            if _alerted.pop(node_id, None) is not None:
                await _notify_recovered(node_id, reading)
            continue
        if ratio >= COLLAPSE_RATIO:
            continue  # down but not off a cliff; not this alarm's business

        _streak[node_id] = _streak.get(node_id, 0) + 1
        if _streak[node_id] < CONFIRMATIONS:
            continue
        if now - _alerted.get(node_id, 0.0) < ALERT_COOLDOWN:
            continue
        _alerted[node_id] = now

        logger.warning(
            "Node %d: traffic collapsed to %.1f%% of its usual for these "
            "hours (%.1f MB/h against %.1f MB/h; fleet at %.0f%%)",
            node_id, reading.ratio * 100,
            reading.recent_per_hour / (1 << 20),
            reading.baseline_per_hour / (1 << 20), fleet * 100,
        )
        await _notify_collapse(node_id, reading, fleet)


def _fleet_ratio(readings: dict) -> float:
    """How the whole fleet is doing against its own week, right now."""
    recent = sum(r.recent_per_hour for r in readings.values())
    baseline = sum(r.baseline_per_hour for r in readings.values())
    if baseline <= 0:
        return 1.0
    # A fleet that has genuinely almost stopped would divide everything up to
    # "normal" and silence the alarm exactly when it matters most.
    return max(recent / baseline, FLEET_FLOOR)


def _node_address(node_id: int) -> str:
    node = node_registry.get(node_id)
    return getattr(node, "_address", "unknown") if node else "unknown"


async def _notify_collapse(node_id: int, reading, fleet: float) -> None:
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

    address = _node_address(node_id)
    text = (
        f"⚠️ <b>#TrafficCollapse — узел жив, но трафик ушёл</b>\n"
        f"➖➖➖➖➖➖➖➖➖\n"
        f"{build_node_lines(node_id, address, registered_node_name(node_id))}\n"
        f"<b>Сейчас:</b> {reading.recent_per_hour / (1 << 20):.1f} МБ/ч\n"
        f"<b>Обычно в эти часы:</b> "
        f"{reading.baseline_per_hour / (1 << 20):.1f} МБ/ч "
        f"({reading.ratio * 100:.1f}%)\n"
        f"<b>Парк целиком сейчас:</b> {fleet * 100:.0f}% от своей нормы\n"
        f"➖➖➖➖➖➖➖➖➖\n"
        f"Статус, порт и ключи такую поломку не показывают. Первым делом "
        f"проверить фронт маскировки — мёртвый <code>dest</code> ломает "
        f"рукопожатие под любым именем:\n"
        f"<code>python3 reality_front_probe.py --node {address}</code>"
        f"{admin_tags}"
    )
    try:
        await send_message(text)
    except Exception:
        logger.exception("Failed to send traffic-collapse alert for %d", node_id)


async def _notify_recovered(node_id: int, reading) -> None:
    from app.notification.node_alerts import build_node_lines
    from app.notification.telegram import send_message

    text = (
        f"✅ <b>#TrafficCollapse — трафик вернулся</b>\n"
        f"➖➖➖➖➖➖➖➖➖\n"
        f"{build_node_lines(node_id, _node_address(node_id), registered_node_name(node_id))}\n"
        f"<b>Сейчас:</b> {reading.recent_per_hour / (1 << 20):.1f} МБ/ч "
        f"({reading.ratio * 100:.0f}% от обычного)"
    )
    try:
        await send_message(text)
    except Exception:
        logger.exception("Failed to send traffic-recovery note for %d", node_id)
