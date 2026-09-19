"""Проверять, что нода везёт тех юзеров, которых панель ей отправляла.

До сих пор проверки не было вовсе. Панель толкает изменения по одному и
считает дело сделанным; единственная полная сверка — ``RepopulateUsers`` при
переподключении. Значит, потерянная посылка живёт до следующего обрыва связи,
а если нода стоит месяцами без обрывов — месяцами. Ровно так и случилось с
правкой сервиса: обновления пачкой уходили в очередь глубиной в один слот и
молча пропадали, а узнали мы об этом от человека, который заплатил и не
получил доступ.

Сверка дешёвая: нода отдаёт отпечаток своего набора юзеров (``GetUsersDigest``),
панель считает такой же по своей БД. Совпало — дальше. Не совпало дважды
подряд — значит это не гонка с обновлением, которое ещё летит, и ноде
отправляется полная выгрузка.

Почему два раза. Между запросом отпечатка и выборкой из БД проходит время, и
любое обновление, пойманное на лету, честно даёт расхождение. Один тик — это
подозрение, два подряд — состояние.
"""

import asyncio
import logging
import time

from app.db import GetDB, crud
from app.marznode.registry import node_registry
from app.marznode.users_digest import digest_of_node_users

logger = logging.getLogger(__name__)

# Сколько тиков подряд расхождение должно продержаться, прежде чем чинить.
CONFIRMATIONS = 2
# Одна нода не должна слать письмо каждые пять минут, если течёт постоянно.
ALERT_COOLDOWN = 3600

# node_id -> сколько тиков подряд отпечатки расходятся
_streak: dict[int, int] = {}
# node_id -> когда последний раз о нём писали
_last_alert: dict[int, float] = {}
# Ноды со старым marznode: сказать один раз и больше не трогать.
_unsupported: set[int] = set()


def _expected(node_id: int) -> tuple[int, str]:
    with GetDB() as db:
        return digest_of_node_users(crud.get_node_users(db, node_id))


async def check_node_drift() -> None:
    for node_id, node in node_registry.items():
        if node_id in _unsupported or not getattr(node, "synced", False):
            continue
        try:
            await _check_one(node_id, node)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("node %d: drift check failed", node_id)


async def _check_one(node_id: int, node) -> None:
    try:
        node_count, node_digest = await node.get_users_digest()
    except NotImplementedError:
        _unsupported.add(node_id)
        logger.info(
            "node %d: старый marznode без GetUsersDigest, сверка пропускается",
            node_id,
        )
        return
    except Exception as exc:  # noqa: BLE001
        # Недоступная нода — не наша тревога, о ней говорит монитор канала.
        logger.debug("node %d: digest unavailable (%s)", node_id, exc)
        _streak.pop(node_id, None)
        return

    want_count, want_digest = await asyncio.to_thread(_expected, node_id)

    if node_digest == want_digest:
        if _streak.pop(node_id, None):
            logger.info("node %d: расхождение не подтвердилось", node_id)
        return

    streak = _streak.get(node_id, 0) + 1
    _streak[node_id] = streak
    logger.warning(
        "node %d: набор юзеров разошёлся (на ноде %d, ожидается %d), "
        "подтверждение %d из %d",
        node_id,
        node_count,
        want_count,
        streak,
        CONFIRMATIONS,
    )
    if streak < CONFIRMATIONS:
        return

    _streak.pop(node_id, None)
    try:
        await node.resync_users()
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("node %d: сверка не удалась: %s", node_id, exc)
        await _notify(node_id, node_count, want_count, repaired=False)
        return
    await _notify(node_id, node_count, want_count, repaired=True)


async def _notify(
    node_id: int, node_count: int, want_count: int, repaired: bool
) -> None:
    now = time.time()
    if now - _last_alert.get(node_id, 0) < ALERT_COOLDOWN:
        return
    _last_alert[node_id] = now

    from app.marznode.database import _address_cache, node_name
    from app.notification.node_alerts import build_node_lines
    from app.notification.telegram import send_message

    address = _address_cache.get(node_id, "unknown")
    tail = (
        "Отправлена полная выгрузка, набор приведён к тому, что в панели."
        if repaired
        else "Выгрузку отправить не удалось — набор на ноде остался прежним."
    )
    text = (
        f"⚠️ <b>#NodeDrift — на ноде не те юзеры</b>\n"
        f"➖➖➖➖➖➖➖➖➖\n"
        f"{build_node_lines(node_id, address, node_name(node_id))}\n"
        f"<b>На ноде:</b> {node_count}\n"
        f"<b>Ожидается:</b> {want_count}\n"
        f"➖➖➖➖➖➖➖➖➖\n"
        f"{tail} Если это повторяется на одной и той же ноде, теряются "
        f"обновления по пути, а не разово."
    )
    try:
        await send_message(text)
    except Exception:
        logger.exception("Failed to send drift alert for node %d", node_id)
