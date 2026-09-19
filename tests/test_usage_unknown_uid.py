"""Нода присылает и трафик, который некому приписать.

xray считает всё, что прошло через инбаунд, и то, что не привязано ни к
одному клиенту, приезжает в статистике с uid 0. В панели uid — это
``users.id``, поэтому INSERT в ``node_user_usages`` и ``user_devices``
падает на внешнем ключе: вместе с чужой строкой теряется вся пачка за тик,
а сессия остаётся сломанной до конца цикла. Значит, такие uid надо
отсеивать до первой записи.
"""

import logging

import pytest

from app.tasks import record_usages
from app.utils.device_tracker import track_user_connection


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Users:
    """«База», в которой есть ровно перечисленные id."""

    def __init__(self, *known):
        self.known = set(known)
        self.asked = []

    def scalars(self, statement):
        asked = statement.whereclause.right.value
        self.asked.append(sorted(asked))
        return _Rows(sorted(self.known.intersection(asked)))


class _EmptyDB:
    """Сессия, в которой ничего не находится и ничего не записывается."""

    def __init__(self):
        self.added = []

    def query(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return None

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        pass


def _stat(uid, value=100):
    return {"uid": uid, "value": value, "remote_ip": "10.0.0.1"}


@pytest.fixture(autouse=True)
def forget_complaints():
    record_usages._unknown_uids_logged.clear()
    yield
    record_usages._unknown_uids_logged.clear()


def test_uid_without_a_user_is_dropped():
    filtered = record_usages.drop_unknown_users(
        _Users(63), {44: [_stat(0), _stat(63)]}
    )
    assert filtered == {44: [_stat(63)]}


def test_known_uids_pass_through_untouched():
    api_params = {7: [_stat(1)], 9: [_stat(2)]}
    assert (
        record_usages.drop_unknown_users(_Users(1, 2), api_params)
        is api_params
    )


def test_the_whole_fleet_costs_one_lookup():
    db = _Users(1)
    record_usages.drop_unknown_users(
        db, {7: [_stat(1), _stat(0)], 9: [_stat(2)]}
    )
    assert db.asked == [[0, 1, 2]]


def test_the_same_orphan_is_shouted_about_once(caplog):
    with caplog.at_level(logging.DEBUG, logger="app.tasks.record_usages"):
        for _ in range(3):
            record_usages.drop_unknown_users(
                _Users(63), {44: [_stat(0), _stat(63)]}
            )
    assert [r.levelname for r in caplog.records] == [
        "WARNING",
        "DEBUG",
        "DEBUG",
    ]


def test_unknown_uid_never_reaches_user_devices(caplog):
    """Второй рубеж: даже вызванный напрямую трекер ничего не пишет.

    Одного DEBUG в логе достаточно, чтобы отличить честный отказ от
    проглоченного исключения — оно ушло бы в ERROR.
    """
    db = _EmptyDB()
    with caplog.at_level(logging.DEBUG, logger="app.utils.device_tracker"):
        assert track_user_connection(
            db=db, user_id=0, node_id=44, remote_ip="10.0.0.1"
        ) == (None, None)
    assert db.added == []
    assert [r.levelname for r in caplog.records] == ["DEBUG"]
