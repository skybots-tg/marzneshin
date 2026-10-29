"""Tell the admins what bridge_transit moved, and when it could not.

``tools/bridge_transit.py`` runs on the host every 30 minutes and sends RU legs
that Russia cut through a Russian relay that still gets through. It records
every move, give-back and rollback in ``bridge_transit.status``; this turns the
new ones into one #BridgeTransit message per run. A move is news, not a call
to act -- the hosts on it come back by themselves once the audit sees two clean
runs -- so only rollbacks and legs with no working path tag the admins.

Like #FrontReach, it remembers what it has told in a file next to the status,
so a panel restart does not repeat a message, and the events that were already
there when the alarm first ran are history, not news.
"""

import html
import json
import logging
import os
import time

from app.services.bridge_health_service import DATA_DIR

logger = logging.getLogger(__name__)

STATUS_PATH = os.path.join(DATA_DIR, "bridge_transit.status")
NOTIFIED_PATH = os.path.join(DATA_DIR, "bridge_transit.notified.json")
# The timer fires every 30 minutes and a run may skip itself while a hand run
# of the relay installer holds the lock; two hours of silence is a stopped
# timer.
STALE_SEC = 2 * 3600
STALE_ALERT_COOLDOWN = 6 * 3600
SHOWN = 12

_last_stale_alert_ts: float = 0.0


def _read(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError, OSError):
        return None


def _write(path: str, data) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)


async def check_bridge_transit() -> None:
    status = _read(STATUS_PATH)
    if status is None:
        return  # the host-side timer was never installed here
    await _check_stale(status)
    await _check_events(status)


async def _check_events(status: dict) -> None:
    notified = _read(NOTIFIED_PATH)
    first_run = notified is None
    told = set((notified or {}).get("told") or [])
    events = [e for e in status.get("events") or [] if e.get("id")]
    if first_run:
        told |= {e["id"] for e in events}
    new = [e for e in events if e["id"] not in told]
    if new:
        logger.info("bridge transit: %s", ", ".join(
            f"{e.get('kind')} {e.get('leg')}" for e in new))
        if await notify_events(new):
            told |= {e["id"] for e in new}
    live = {e["id"] for e in events}
    state = {"told": sorted(told & live)}
    if first_run or state != notified:
        try:
            _write(NOTIFIED_PATH, state)
        except OSError:
            logger.exception("cannot save %s", NOTIFIED_PATH)


async def _check_stale(status: dict) -> None:
    global _last_stale_alert_ts

    age = int(time.time()) - int(status.get("updated_at") or 0)
    if age <= STALE_SEC:
        return
    now = time.monotonic()
    if now - _last_stale_alert_ts < STALE_ALERT_COOLDOWN:
        return
    _last_stale_alert_ts = now
    logger.warning("bridge transit status is %d min old", age // 60)
    await notify_stale(age // 60)


def _pct(share) -> str:
    return "—" if share is None else f"{round(float(share) * 100)}%"


def _short(name) -> str:
    """'50 🇷🇺 Webhost1.ru RU-2' -> '50 Webhost1.ru RU-2'; 'direct' -> 'напрямую'."""
    name = str(name or "")
    if name == "direct":
        return "напрямую"
    return " ".join(p for p in name.split() if not all(0x1F1E6 <= ord(c) <= 0x1F1FF for c in p))


def _leg(e: dict) -> str:
    return (f"{html.escape(_short(e.get('src')))} → <code>{html.escape(str(e.get('tag') or ''))}</code>"
            + (f" ({html.escape(_short(e.get('dst')))})" if e.get("dst") else ""))


def _move(e: dict) -> str:
    return (f"• {_leg(e)}: {html.escape(_short(e.get('from_name') or e.get('from')))} → "
            f"{html.escape(_short(e.get('to_name') or e.get('to')))}, "
            f"было {_pct(e.get('before'))}, стало {_pct(e.get('after'))}")


def _admin_tags() -> str:
    from app.config.env import TELEGRAM_ADMIN_ID

    if not TELEGRAM_ADMIN_ID:
        return ""
    return "\n" + " ".join(
        f'<a href="tg://user?id={uid}">admin</a>' for uid in TELEGRAM_ADMIN_ID
    )


async def _send(text: str) -> bool:
    from app.notification.telegram import send_message

    try:
        await send_message(text)
    except Exception:
        logger.exception("Failed to send bridge-transit message")
        return False
    return True


def _section(title: str, lines: list[str]) -> list[str]:
    if not lines:
        return []
    more = [f"…и ещё {len(lines) - SHOWN}"] if len(lines) > SHOWN else []
    return [f"<b>{title}</b>", *lines[:SHOWN], *more]


async def notify_events(events: list[dict]) -> bool:
    by_kind: dict[str, list[dict]] = {}
    for e in events:
        by_kind.setdefault(e.get("kind"), []).append(e)
    body = (
        _section("Переведены через релей:", [_move(e) for e in by_kind.get("moved", [])])
        + _section("Вернулись на свой путь:", [_move(e) for e in by_kind.get("returned", [])])
        + _section("Откачены — с релеем не лучше:",
                   [_move(e) for e in by_kind.get("rolled_back", [])])
        + _section("Нет рабочего пути:", [
            f"• {_leg(e)}: {_pct(e.get('share'))}, лучший релей {_pct(e.get('best'))}"
            for e in by_kind.get("no_path", [])])
        + _section("Плечо ушло из конфига, строка снята:",
                   [f"• {_leg(e)}" for e in by_kind.get("gone", [])])
    )
    if not body:
        return True
    needs_human = bool(by_kind.get("rolled_back") or by_kind.get("no_path"))
    head = ("⚠️ <b>#BridgeTransit — путь не нашёлся</b>" if needs_human
            else "🔀 <b>#BridgeTransit — пути перестроены</b>")
    text = (
        f"{head}\n➖➖➖➖➖➖➖➖➖\n" + "\n".join(body) + "\n➖➖➖➖➖➖➖➖➖\n"
        "Скрытые хосты на починенных плечах аудит вернёт сам после двух чистых "
        "прогонов (~30 мин).\n"
        "<code>python3 /opt/marzneshin/tools/bridge_transit.py status</code>"
        + (_admin_tags() if needs_human else "")
    )
    return await _send(text)


async def notify_stale(stale_minutes: int) -> None:
    text = (
        f"⚠️ <b>#BridgeTransit — автотранзит не работает</b>\n"
        f"➖➖➖➖➖➖➖➖➖\n"
        f"<b>Последний прогон:</b> {stale_minutes} мин назад\n"
        f"➖➖➖➖➖➖➖➖➖\n"
        f"Пока он стоит, перерезанные плечи RU-нод никто не переводит через релей.\n"
        f"<code>systemctl status marz-bridge-transit.timer</code>\n"
        f"<code>tail -50 /var/lib/marzneshin/bridge_transit.log</code>"
    )
    await _send(text)
