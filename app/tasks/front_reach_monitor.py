"""Alert when a node stops reaching its own REALITY front, and when it is back.

The other front alarm (``reality_front_monitor``) reads a daily handshake test
and answers "can this site front for us". This one answers "does it still
answer this node", every five minutes — the question that mattered on
2026-10-01, when www.elisa.ee banned EE-1's address in waves of 30–60 minutes.
xray dials ``dest`` before it reads the client hello, so while the front is
silent no new connection gets through, for anyone; from outside the node
stays healthy and just piles up connections.

The probing and the episode bookkeeping happen on the host in
``tools/front_reach.py`` (the panel container has no ssh). This turns the
episodes it records into two messages each — one when it opens, one when it
closes — and remembers which ones it has told about in a file next to the
status, so a panel restart in the middle of an outage does not repeat itself.
"""

import html
import json
import logging
import os
import time

from app.services.bridge_health_service import DATA_DIR

logger = logging.getLogger(__name__)

STATUS_PATH = os.path.join(DATA_DIR, "front_reach.status")
NOTIFIED_PATH = os.path.join(DATA_DIR, "front_reach.notified.json")
# The check runs every five minutes; half an hour without a status is a
# stopped timer. A skipped run still stamps the status.
STALE_SEC = 30 * 60
STALE_ALERT_COOLDOWN = 6 * 3600

RESOLUTIONS = {
    "recovered": "фронт снова отвечает",
    "front_replaced": "фронт заменён",
    "node_removed": "нода удалена из панели",
}

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


async def check_front_reach() -> None:
    report = _read(STATUS_PATH)
    if report is None:
        return  # the host-side timer was never installed here
    await _check_stale(report)
    await _check_episodes(report)


async def _check_episodes(report: dict) -> None:
    notified = _read(NOTIFIED_PATH)
    first_run = notified is None
    notified = notified or {}
    opened_ids = set(notified.get("opened") or [])
    closed_ids = set(notified.get("closed") or [])

    open_eps = [ep for ep in report.get("open") or [] if ep.get("id")]
    closed_eps = [ep for ep in report.get("closed") or [] if ep.get("id")]

    if first_run:
        # Episodes that ended before this alarm existed are history, not news.
        closed_ids |= {ep["id"] for ep in closed_eps}

    new_open = [ep for ep in open_eps if ep["id"] not in opened_ids]
    new_closed = [ep for ep in closed_eps if ep["id"] not in closed_ids]

    if new_open:
        logger.warning(
            "front unreachable: %s",
            ", ".join(f"node {ep['node_id']} {ep['front']}" for ep in new_open),
        )
        if await notify_unreachable(new_open):
            opened_ids |= {ep["id"] for ep in new_open}
    if new_closed:
        logger.info(
            "front reachable again: %s",
            ", ".join(f"node {ep['node_id']} {ep['front']}" for ep in new_closed),
        )
        if await notify_recovered(new_closed, opened_ids):
            closed_ids |= {ep["id"] for ep in new_closed}

    # Forget what the status no longer carries; it cannot come back.
    live = {ep["id"] for ep in open_eps} | {ep["id"] for ep in closed_eps}
    state = {"opened": sorted(opened_ids & live),
             "closed": sorted(closed_ids & live)}
    if first_run or state != notified:
        try:
            _write(NOTIFIED_PATH, state)
        except OSError:
            logger.exception("cannot save %s", NOTIFIED_PATH)


async def _check_stale(report: dict) -> None:
    global _last_stale_alert_ts

    age = int(time.time()) - int(report.get("generated_at") or 0)
    if age <= STALE_SEC:
        return
    now = time.monotonic()
    if now - _last_stale_alert_ts < STALE_ALERT_COOLDOWN:
        return
    _last_stale_alert_ts = now

    logger.warning("front reach check is %d min old", age // 60)
    await notify_check_stale(age // 60)


def _hm(ts) -> str:
    return time.strftime("%H:%M", time.gmtime(int(ts)))


def _duration(seconds: int) -> str:
    minutes = max(0, int(seconds)) // 60
    if minutes < 60:
        return f"{minutes} мин"
    return f"{minutes // 60} ч {minutes % 60:02d} мин"


def _admin_tags() -> str:
    from app.config.env import TELEGRAM_ADMIN_ID

    if not TELEGRAM_ADMIN_ID:
        return ""
    return "\n" + " ".join(
        f'<a href="tg://user?id={uid}">admin</a>' for uid in TELEGRAM_ADMIN_ID
    )


def _node(ep: dict) -> str:
    return (f"нода <code>{ep['node_id']}</code> "
            f"{html.escape(str(ep.get('name') or ''))}").rstrip()


async def _send(text: str) -> bool:
    from app.notification.telegram import send_message

    try:
        await send_message(text)
    except Exception:
        logger.exception("Failed to send front-reach alert")
        return False
    return True


async def notify_unreachable(episodes: list[dict]) -> bool:
    lines = []
    for ep in episodes[:10]:
        ips = ", ".join(ep.get("ips") or []) or "—"
        lines.append(
            f"• {_node(ep)} → <code>{html.escape(ep['front'])}</code> "
            f"({html.escape(ips)}), с {_hm(ep['started_at'])} UTC\n"
            f"   {html.escape(str(ep.get('reason') or ''))}; "
            f"SYN-SENT: {int(ep.get('max_syn_sent') or 0)}, "
            f"инбаундов: {int(ep.get('inbounds') or 0)}"
        )
    more = f"\n…и ещё {len(episodes) - 10}" if len(episodes) > 10 else ""
    address = episodes[0].get("address") or "&lt;ip&gt;"
    text = (
        f"🚨 <b>#FrontReach — нода не достаёт до своего фронта</b>\n"
        f"➖➖➖➖➖➖➖➖➖\n"
        + "\n".join(lines) + more + "\n"
        f"➖➖➖➖➖➖➖➖➖\n"
        f"xray дозванивается до <code>dest</code> раньше, чем читает "
        f"приветствие клиента: пока фронт молчит, на ноду не проходит ни одно "
        f"новое подключение, у всех. Если фронт жив из Норвегии — он забанил "
        f"адрес ноды; подобрать замену и переставить (фаза 3):\n"
        f"<code>python3 reality_front_probe.py --node {html.escape(address)}</code>\n"
        f"<code>python3 reality_front_apply.py --exit {html.escape(address)} "
        f"--front &lt;домен&gt; --phase 1|3 --apply</code>"
        f"{_admin_tags()}"
    )
    return await _send(text)


async def notify_recovered(episodes: list[dict], announced: set[str]) -> bool:
    lines = []
    for ep in episodes[:10]:
        how = RESOLUTIONS.get(ep.get("resolution"), ep.get("resolution") or "")
        unseen = "" if ep["id"] in announced else " (начало не сообщалось)"
        lines.append(
            f"• {_node(ep)} → <code>{html.escape(ep['front'])}</code>: "
            f"{_hm(ep['started_at'])}–{_hm(ep['ended_at'])} UTC, "
            f"{_duration(int(ep['ended_at']) - int(ep['started_at']))} — "
            f"{html.escape(how)}{unseen}"
        )
    more = f"\n…и ещё {len(episodes) - 10}" if len(episodes) > 10 else ""
    text = (
        f"✅ <b>#FrontReach — фронт снова доступен</b>\n"
        f"➖➖➖➖➖➖➖➖➖\n"
        + "\n".join(lines) + more + "\n"
        f"➖➖➖➖➖➖➖➖➖\n"
        f"История: <code>/var/lib/marzneshin/front_reach.episodes.jsonl</code>"
    )
    return await _send(text)


async def notify_check_stale(stale_minutes: int) -> None:
    text = (
        f"⚠️ <b>#FrontReach — проверка доступности фронтов не идёт</b>\n"
        f"➖➖➖➖➖➖➖➖➖\n"
        f"<b>Последняя:</b> {stale_minutes} мин назад\n"
        f"➖➖➖➖➖➖➖➖➖\n"
        f"<code>systemctl status marz-front-reach.timer</code>\n"
        f"<code>tail /var/lib/marzneshin/front_reach.log</code>"
    )
    await _send(text)
