"""Alert when a node's masking front stops being able to front for it.

A REALITY listener serves the handshake of ``dest`` — a real site it pretends
to be — so ``dest`` is a third-party dependency sitting in the critical path of
every connection. It changes on somebody else's schedule and takes the node
down with it: ``www.free.fr`` dropped TLS 1.3 and both French exits refused
every subscriber for three days while answering their ports, holding their
keys and reporting healthy. No check in the fleet was pointed at it.

The measuring is done on the host by ``tools/front_watch.py`` (the panel
container has no ssh); this reads what it wrote. Two things can be wrong, and
they are different: a front that fails its handshake, and a check that stopped
running — the second one hides the first, which is the shape of every
monitoring failure this fleet has had.
"""

import json
import logging
import os
import time

from app.services.bridge_health_service import DATA_DIR

logger = logging.getLogger(__name__)

STATUS_PATH = os.path.join(DATA_DIR, "reality_fronts.status")
# The check runs daily. Two days without one is a stopped timer, not a slow day.
STALE_SEC = 48 * 3600
ALERT_COOLDOWN = 6 * 3600

_last_alert_ts: float = 0.0
_last_stale_alert_ts: float = 0.0


def _load() -> dict | None:
    try:
        with open(STATUS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError, OSError):
        return None


async def check_reality_fronts() -> None:
    report = _load()
    if report is None:
        return  # never run here; nothing to say
    await _check_broken(report)
    await _check_stale(report)


async def _check_broken(report: dict) -> None:
    global _last_alert_ts

    broken = [f for f in report.get("fronts", [])
              if "error" not in f and not f.get("usable")]
    if not broken:
        return
    now = time.monotonic()
    if now - _last_alert_ts < ALERT_COOLDOWN:
        return
    _last_alert_ts = now

    logger.warning("%d masking front(s) no longer usable", len(broken))
    await notify_front_broken(broken)


async def _check_stale(report: dict) -> None:
    global _last_stale_alert_ts

    age = int(time.time()) - int(report.get("generated_at") or 0)
    if age <= STALE_SEC:
        return
    now = time.monotonic()
    if now - _last_stale_alert_ts < ALERT_COOLDOWN:
        return
    _last_stale_alert_ts = now

    logger.warning("reality front check is %d h old", age // 3600)
    await notify_front_check_stale(age // 3600)


def _reason(front: dict) -> str:
    missing = [label for key, label in (
        ("tls13", "TLS 1.3"), ("x25519", "X25519"),
        ("h2", "h2"), ("cert_covers", "сертификат"),
    ) if not front.get(key)]
    return ", ".join(missing) or "рукопожатие не собирается"


async def notify_front_broken(broken: list[dict]) -> None:
    from app.config.env import TELEGRAM_ADMIN_ID
    from app.notification.telegram import send_message

    admin_tags = ""
    if TELEGRAM_ADMIN_ID:
        tags = " ".join(
            f'<a href="tg://user?id={uid}">admin</a>'
            for uid in TELEGRAM_ADMIN_ID
        )
        admin_tags = f"\n{tags}"

    lines = "\n".join(
        f"• нода <code>{f['node_id']}</code> {f.get('name') or ''} — "
        f"<code>{f['front']}</code> ({_reason(f)}), "
        f"инбаундов: {len(f.get('inbounds') or [])}"
        for f in broken[:10]
    )
    more = (f"\n…и ещё {len(broken) - 10}" if len(broken) > 10 else "")

    text = (
        f"⚠️ <b>#RealityFront — фронт маскировки сломался</b>\n"
        f"➖➖➖➖➖➖➖➖➖\n"
        f"{lines}{more}\n"
        f"➖➖➖➖➖➖➖➖➖\n"
        f"REALITY отдаёт клиенту рукопожатие, снятое с <code>dest</code>: "
        f"пока он мёртв, узел отказывает всем и под любым именем, оставаясь "
        f"снаружи здоровым. Подобрать замену и раскатать:\n"
        f"<code>python3 reality_front_probe.py --node &lt;ip&gt;</code>\n"
        f"<code>python3 reality_front_apply.py --exit &lt;ip&gt; --front &lt;домен&gt; "
        f"--phase 1|2|3 --apply</code>\n"
        f"Чинит только фаза 3 — она переставляет сам <code>dest</code>."
        f"{admin_tags}"
    )
    try:
        await send_message(text)
    except Exception:
        logger.exception("Failed to send reality-front alert")


async def notify_front_check_stale(stale_hours: int) -> None:
    from app.notification.telegram import send_message

    text = (
        f"⚠️ <b>#RealityFront — проверка фронтов не идёт</b>\n"
        f"➖➖➖➖➖➖➖➖➖\n"
        f"<b>Последняя:</b> {stale_hours} ч назад\n"
        f"➖➖➖➖➖➖➖➖➖\n"
        f"<code>systemctl status marz-front-watch.timer</code>"
    )
    try:
        await send_message(text)
    except Exception:
        logger.exception("Failed to send reality-front staleness alert")
