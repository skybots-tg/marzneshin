"""Отпечаток набора юзеров — общий формат для панели и ноды.

Формат описан здесь и во второй его реализации,
``marznode/utils/users_digest.py`` в репозитории ноды; разойтись они не
должны, поэтому в тестах обеих сторон лежит одна и та же фикстура с одним и
тем же ожидаемым хэшем.

* на юзера — строка ``"<id>:<tag>,<tag>,..."``;
* теги внутри строки отсортированы и дедуплицированы;
* строки отсортированы как строки (``"10:"`` идёт раньше ``"9:"`` — это не
  ошибка, важно лишь чтобы обе стороны сортировали одинаково);
* всё склеено через ``"\n"``, от utf-8 берётся sha256, отдаётся hex.

Второй отпечаток, ``keyed_users_digest``, устроен так же, но в строке юзера
между id и тегами стоит его ключ: ``"<id>:<key>:<tag>,<tag>,..."``. Первый
смену ключа не видит: 07.10.2026 перевыпущенная ссылка не доехала до нод, они
пускали по старому ключу и сверку при этом проходили. Старые ноды второго не
отдают — их сверяем по первому.
"""

import hashlib
from typing import Iterable


def users_digest(users: Iterable[tuple[int, Iterable[str]]]) -> str:
    """sha256 по парам (id юзера, его инбаунд-теги)."""
    lines = sorted(
        "{}:{}".format(uid, ",".join(sorted(set(tags)))) for uid, tags in users
    )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def keyed_users_digest(users: Iterable[tuple[int, str, Iterable[str]]]) -> str:
    """sha256 по тройкам (id юзера, его ключ, его инбаунд-теги)."""
    lines = sorted(
        "{}:{}:{}".format(uid, key, ",".join(sorted(set(tags))))
        for uid, key, tags in users
    )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def digest_of_node_users(node_users: Iterable[dict]) -> tuple[int, str, str]:
    """(сколько юзеров, отпечаток, отпечаток с ключами) для выдачи
    ``crud.get_node_users``."""
    rows = [(u["id"], u["key"], u["inbounds"]) for u in node_users]
    return (
        len(rows),
        users_digest((uid, tags) for uid, _, tags in rows),
        keyed_users_digest(rows),
    )
