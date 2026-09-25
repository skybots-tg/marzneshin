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

import html
import json
import logging
import os
import time

from app.services.bridge_health_service import (
    FULL_SWEEP_SILENT_SEC,
    QUICK_REPORT_PATH,
    REPORT_PATH,
    STATE_PATH,
    STATUS_PATH,
    WATCHDOG_SILENT_SEC,
)

logger = logging.getLogger(__name__)

ALERT_COOLDOWN = 6 * 3600

# Failures in a row after which a hide the audit is holding back stops being a
# thin verdict. The same bar as ``HIDE_CONFIDENT_STREAK`` in
# tools/bridge_state.py -- two hours of quick runs.
HELD_HIDE_STREAK = 8

# Why the audit held a hide, as a human should read it.
HELD_REASONS = {
    "last_visible_entry": "последний видимый хост входа",
    "last_visible_slot": "последний видимый хост страны",
    "rate_limit_run": "лимит скрытий за прогон",
    "rate_limit_day": "дневной лимит скрытий",
}

_last_alert_ts: float = 0.0
_last_sweep_alert_ts: float = 0.0
_held_alert_ts: dict[str, float] = {}


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


def _full_sweep_age() -> int | None:
    """Seconds since the last *complete* sweep, or None if unknowable."""
    try:
        with open(REPORT_PATH, encoding="utf-8") as f:
            stamp = int(json.load(f).get("generated_at") or 0)
    except (FileNotFoundError, ValueError, OSError):
        return None
    if not stamp:
        return None
    return max(0, int(time.time()) - stamp)


def _last_exit_code() -> int | None:
    try:
        with open(STATUS_PATH, encoding="utf-8") as f:
            return json.load(f).get("rc")
    except (FileNotFoundError, ValueError, OSError):
        return None


def _held_hides() -> dict[str, dict]:
    """Links the audit has long wanted hidden but is holding for a human."""
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            links = json.load(f).get("links") or {}
    except (FileNotFoundError, ValueError, OSError, AttributeError):
        return {}
    return {
        key: s for key, s in links.items()
        if s.get("verdict") == "down" and s.get("deferred")
        and int(s.get("fail_streak") or 0) >= HELD_HIDE_STREAK
    }


def _visible_hosts_by_link() -> dict[str, list[tuple[int, str]]] | None:
    """link -> its visible (host id, remark), from the freshest report.

    None when there is no report to read, which is not the same as "nothing
    is visible".
    """
    reports = []
    for path in (QUICK_REPORT_PATH, REPORT_PATH):
        try:
            with open(path, encoding="utf-8") as f:
                reports.append(json.load(f))
        except (FileNotFoundError, ValueError, OSError):
            continue
    if not reports:
        return None
    newest = max(reports, key=lambda r: int(r.get("generated_at") or 0))
    out: dict[str, list[tuple[int, str]]] = {}
    for h in newest.get("hosts") or []:
        if h.get("is_disabled") or not h.get("link"):
            continue
        out.setdefault(h["link"], []).append(
            (int(h.get("host_id") or 0), str(h.get("remark") or "")))
    return out


async def check_bridge_watchdog() -> None:
    if not os.path.exists(STATE_PATH):
        return  # the audit has never run here; nothing to be silent about
    await _check_verdicts_silent()
    await _check_full_sweep_silent()
    await _check_held_hides()


async def _check_held_hides() -> None:
    """A dead host the audit will not hide on its own, told to a human.

    The floors in ``bridge_state`` refuse to take the last visible host of an
    entry or a country quietly, and the rate limits cap how much one run or one
    day may take. Both are right to wait for a person -- and until now the
    only place they said so was ``bridge_audit.log``. #506 and #496 sat
    visible and dead for nine hours on 24.09 with the audit asking to hide them
    every quarter of an hour.
    """
    held = _held_hides()
    visible = _visible_hosts_by_link()
    if visible is not None:
        # A link hidden by hand keeps its held note until the audit next gets
        # round to probing the hidden half: nothing in a subscription to warn
        # about.
        held = {key: s for key, s in held.items() if visible.get(key)}
    # A link that recovered or got hidden is off the list; if it relapses,
    # that is news again.
    for key in list(_held_alert_ts):
        if key not in held:
            _held_alert_ts.pop(key, None)
    now = time.monotonic()
    due = {key: s for key, s in held.items()
           if key not in _held_alert_ts
           or now - _held_alert_ts[key] >= ALERT_COOLDOWN}
    if not due:
        return
    for key in due:
        _held_alert_ts[key] = now

    logger.warning("bridge audit is holding %d dead link(s) for a human: %s",
                   len(due), ", ".join(sorted(due)))
    await notify_held_hides(due, visible or {})


async def _check_verdicts_silent() -> None:
    global _last_alert_ts

    age = _decided_age()
    if age is None or age <= WATCHDOG_SILENT_SEC:
        return
    now = time.monotonic()
    if now - _last_alert_ts < ALERT_COOLDOWN:
        return
    _last_alert_ts = now

    logger.warning("bridge audit has not decided anything for %d min", age // 60)
    await notify_watchdog_silent(age // 60, _last_exit_code())


async def _check_full_sweep_silent() -> None:
    """The other half of the failure, which the check above cannot see.

    Two cadences share one runner: a quick check probes one host per link every
    few minutes, and a full sweep redraws the whole picture once a day. Only the
    sweep produces the matrix, the gaps and the per-host detail every decision
    by hand is made from. And because the quick runs keep stamping
    ``scanned_at``, a sweep that has quietly stopped leaves the silence alarm
    above with nothing to complain about — the numbers on the page stay
    plausible while the portrait behind them ages out. The page does mark the
    report stale after a day; nobody is watching the page.
    """
    global _last_sweep_alert_ts

    age = _full_sweep_age()
    if age is None or age <= FULL_SWEEP_SILENT_SEC:
        return
    now = time.monotonic()
    if now - _last_sweep_alert_ts < ALERT_COOLDOWN:
        return
    _last_sweep_alert_ts = now

    logger.warning("bridge audit full sweep is %d h old", age // 3600)
    await notify_full_sweep_stale(age // 3600)


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


async def notify_full_sweep_stale(stale_hours: int) -> None:
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
        f"⚠️ <b>#BridgeWatchdog — полный обход не доходит</b>\n"
        f"➖➖➖➖➖➖➖➖➖\n"
        f"<b>Последний полный отчёт:</b> {stale_hours} ч назад\n"
        f"➖➖➖➖➖➖➖➖➖\n"
        f"Быстрые проверки идут и держат вердикты свежими, поэтому вторая "
        f"тревога молчит. Но матрица, пробелы и детали по хостам с тех пор "
        f"не перерисовывались — решения руками принимать не из чего:\n"
        f"<code>tail /var/lib/marzneshin/bridge_audit.log</code>"
        f"{admin_tags}"
    )

    try:
        await send_message(text)
    except Exception:
        logger.exception("Failed to send bridge-watchdog alert")


async def notify_held_hides(held: dict[str, dict],
                            hosts_by_link: dict[str, list[tuple[int, str]]]
                            ) -> None:
    from app.config.env import TELEGRAM_ADMIN_ID
    from app.notification.telegram import send_message

    admin_tags = ""
    if TELEGRAM_ADMIN_ID:
        tags = " ".join(
            f'<a href="tg://user?id={uid}">admin</a>'
            for uid in TELEGRAM_ADMIN_ID
        )
        admin_tags = f"\n{tags}"

    lines = []
    for key, s in sorted(held.items()):
        why = HELD_REASONS.get(s.get("deferred"), s.get("deferred"))
        lines.append(
            f"<code>{html.escape(key)}</code> — "
            f"{int(s.get('fail_streak') or 0)} провалов подряд, "
            f"держит: {html.escape(str(why))}"
        )
        for host_id, remark in hosts_by_link.get(key, []):
            lines.append(f"    #{host_id} {html.escape(remark)}")

    text = (
        f"⚠️ <b>#BridgeWatchdog — мёртвый хост ждёт человека</b>\n"
        f"➖➖➖➖➖➖➖➖➖\n"
        + "\n".join(lines) + "\n"
        f"➖➖➖➖➖➖➖➖➖\n"
        f"Аудит хочет скрыть эти хосты, но сам не имеет права: это последний "
        f"видимый хост входа или страны, либо исчерпан лимит скрытий. Пока "
        f"они в подписках, клиенты попадают на неработающий сервер. Скрыть "
        f"руками, переключить на рабочий выход или поднять сервер:\n"
        f"<code>python3 /opt/marzneshin/tools/bridge_audit.py matrix</code>"
        f"{admin_tags}"
    )

    try:
        await send_message(text)
    except Exception:
        logger.exception("Failed to send bridge-watchdog alert")
