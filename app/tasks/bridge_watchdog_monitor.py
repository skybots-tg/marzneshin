"""Alert when the bridge audit stops deciding anything.

Its failure is quiet by design, which is what makes it worth a task of its own:
the last report stays on the page, every number on it stays plausible, and the
only symptom is that locations which recovered never come back. Meanwhile the
mechanism is asymmetric -- hiding a host takes one confirmed failure, restoring
it takes two clean runs -- so a stalled audit does not freeze the fleet where it
was, it holds the fleet at its most hidden. It went unnoticed for eleven hours
once, during which a working country stayed out of every subscription.

The host-side runner releases recent hides on its own after a couple of hours
(``bridge_audit.py revive``); this is the part that tells a human, because the
underlying fault -- a wedged vantage, a crash loop, a full disk -- is not
something the automation can repair.
"""

import json
import logging
import os
import time

from app.services.bridge_health_service import (
    STATE_PATH,
    STATUS_PATH,
    WATCHDOG_SILENT_SEC,
)

logger = logging.getLogger(__name__)

ALERT_COOLDOWN = 6 * 3600

_last_alert_ts: float = 0.0


def _decided_age() -> int | None:
    """Seconds since a probe last reached a verdict, or None if unknowable."""
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            state = json.load(f)
    except (FileNotFoundError, ValueError, OSError):
        return None
    stamp = int(state.get("scanned_at") or state.get("updated_at") or 0)
    if not stamp:
        return None
    return max(0, int(time.time()) - stamp)


def _last_exit_code() -> int | None:
    try:
        with open(STATUS_PATH, encoding="utf-8") as f:
            return json.load(f).get("rc")
    except (FileNotFoundError, ValueError, OSError):
        return None


async def check_bridge_watchdog() -> None:
    global _last_alert_ts

    if not os.path.exists(STATE_PATH):
        return  # the audit has never run here; nothing to be silent about
    age = _decided_age()
    if age is None or age <= WATCHDOG_SILENT_SEC:
        return
    now = time.monotonic()
    if now - _last_alert_ts < ALERT_COOLDOWN:
        return
    _last_alert_ts = now

    logger.warning("bridge audit has not decided anything for %d min", age // 60)
    await notify_watchdog_silent(age // 60, _last_exit_code())


async def notify_watchdog_silent(silent_minutes: int, rc: int | None) -> None:
    from app.config.env import TELEGRAM_ADMIN_ID
    from app.notification.telegram import send_message

    admin_tags = ""
    if TELEGRAM_ADMIN_ID:
        tags = " ".join(
            f'<a href="tg://user?id={uid}">admin</a>'
            for uid in TELEGRAM_ADMIN_ID
        )
        admin_tags = f"\n{tags}"

    code = f"\n<b>Код выхода:</b> <code>{rc}</code>" if rc else ""
    text = (
        f"⚠️ <b>#BridgeWatchdog — аудит бриджей молчит</b>\n"
        f"➖➖➖➖➖➖➖➖➖\n"
        f"<b>Без решений:</b> {silent_minutes} мин"
        f"{code}\n"
        f"➖➖➖➖➖➖➖➖➖\n"
        f"Пока он лежит, скрытые хосты не возвращаются сами: "
        f"скрыть — один прогон, вернуть — два. Свежие автогашения "
        f"снимаются автоматически, причину надо смотреть руками:\n"
        f"<code>tail /var/lib/marzneshin/bridge_audit.log</code>"
        f"{admin_tags}"
    )

    try:
        await send_message(text)
    except Exception:
        logger.exception("Failed to send bridge-watchdog alert")
