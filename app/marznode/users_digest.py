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
"""

import hashlib
from typing import Iterable


def users_digest(users: Iterable[tuple[int, Iterable[str]]]) -> str:
    """sha256 по парам (id юзера, его инбаунд-теги)."""
    lines = sorted(
        "{}:{}".format(uid, ",".join(sorted(set(tags)))) for uid, tags in users
    )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def digest_of_node_users(node_users: Iterable[dict]) -> tuple[int, str]:
    """(сколько юзеров, отпечаток) для выдачи ``crud.get_node_users``."""
    rows = [(u["id"], u["inbounds"]) for u in node_users]
    return len(rows), users_digest(rows)
