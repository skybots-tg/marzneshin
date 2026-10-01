"""Запись трафика не должна останавливать панель.

``record_user_usages`` раз в 30 секунд раскладывает статистику нод по базе:
устройства, почасовые логи, ``used_traffic``. Раньше всё это шло прямо в
event loop, и на проде каждый тик API замирал на 0,5–1,8 с (замеры из
perf.log, фаза устройств на 26 нодах). Теперь база пишется в отдельном
потоке (``store_usages``), а в loop остаются опрос нод, пуш пользователя на
ноды и уведомления. Тесты проверяют и то, что loop свободен, пока идёт
запись, и то, что запись при этом считает так же, как раньше.
"""

import asyncio
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import BigInteger, create_engine, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import marznode
from app.db.base import Base
from app.db.models import Admin, Inbound, NodeUsage, NodeUserUsage, Service, User
from app.marznode import operations
from app.marznode.registry import NodeRegistry
from app.models.notification import UserNotification
from app.tasks import node_traffic_monitor, record_usages
from app.utils import async_utils


@compiles(BigInteger, "sqlite")
def _bigint_as_rowid(type_, compiler, **kw):
    # SQLite автоинкрементит только INTEGER PRIMARY KEY, а у таблиц
    # устройств id — BIGINT. На MariaDB это ничего не меняет.
    return "INTEGER"


class _Node:
    """Нода, которая отдаёт заданную статистику и запоминает пуши."""

    def __init__(self, coefficient, stats=()):
        self.usage_coefficient = coefficient
        self.stats = list(stats)
        self.updates = []

    async def fetch_users_stats(self):
        return self.stats

    async def update_user(self, **update):
        self.updates.append((threading.get_ident(), update))


def _stat(uid, usage):
    return SimpleNamespace(uid=uid, usage=usage, uplink=0, downlink=usage)


@pytest.fixture
def nodes(monkeypatch):
    """Пустой реестр нод вместо общего."""
    registry = NodeRegistry()
    monkeypatch.setattr(marznode, "node_registry", registry)
    monkeypatch.setattr(marznode, "nodes", registry._nodes)
    monkeypatch.setattr(operations, "node_registry", registry)
    return registry


@pytest.fixture
def loop_calls(monkeypatch):
    """Уведомления, которые ушли, с потоком, из которого их отправили.

    ``fire_and_forget`` нужен главный loop; сам тест его и запускает, а
    monkeypatch вернёт глобальные значения на место.
    """
    monkeypatch.setattr(async_utils, "_main_loop", None)
    monkeypatch.setattr(async_utils, "_main_thread_id", None)
    monkeypatch.setattr(node_traffic_monitor, "_last_traffic_ts", {})
    record_usages._unknown_uids_logged.clear()

    sent = []

    async def notify(action, user):
        sent.append((threading.get_ident(), action, user))

    monkeypatch.setattr(record_usages, "notify", notify)
    yield sent
    record_usages._unknown_uids_logged.clear()


@pytest.fixture
def engine(monkeypatch):
    # Пустой server_default у admins.subscription_url_prefix SQLite не
    # понимает (``DEFAULT  NOT NULL``); для теста он не нужен.
    monkeypatch.setattr(
        Admin.__table__.c.subscription_url_prefix, "server_default", None
    )
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)

    @contextmanager
    def get_db():
        db = Session(eng)
        try:
            yield db
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    monkeypatch.setattr(record_usages, "GetDB", get_db)
    yield eng
    eng.dispose()


def _run_tick():
    """Один тик планировщика; возвращает id потока, в котором шёл loop."""

    async def scenario():
        async_utils.init_event_loop()
        await record_usages.record_user_usages()
        # fire_and_forget только ставит задачи в очередь; даём им пройти.
        for _ in range(3):
            await asyncio.sleep(0)
        return threading.get_ident()

    return asyncio.run(scenario())


def test_scheduler_job_leaves_the_event_loop_free(
    monkeypatch, nodes, loop_calls
):
    """Пока база пишется, loop успевает отвечать."""
    writers = []

    def slow_store(api_params, coefficients):
        writers.append(threading.get_ident())
        time.sleep(0.5)
        return record_usages.UsageOutcome()

    monkeypatch.setattr(record_usages, "store_usages", slow_store)

    async def scenario():
        async_utils.init_event_loop()
        ticks = 0

        async def heartbeat():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.02)
                ticks += 1

        beat = asyncio.create_task(heartbeat())
        await record_usages.record_user_usages()
        beat.cancel()
        return ticks, threading.get_ident()

    ticks, loop_thread = asyncio.run(scenario())
    assert ticks >= 10
    assert writers and writers[0] != loop_thread


def test_tick_writes_traffic_and_hands_pushes_back_to_the_loop(
    engine, monkeypatch, nodes, loop_calls
):
    """Полный тик на SQLite: что записано в базу и кто что отправил.

    alice переходит порог уведомления (80 %), bob выбирает лимит целиком,
    carol сидит на безлимитной ноде (коэффициент 0), uid 999 в базе нет.
    """
    with Session(engine) as db:
        service = Service(id=1, name="main")
        db.add(
            Inbound(id=1, tag="vless-7", config="{}", node_id=7,
                    services=[service])
        )
        db.add_all([
            User(id=1, username="alice", key="k1", services=[service],
                 data_limit=1000, used_traffic=700),
            User(id=2, username="bob", key="k2", services=[service],
                 data_limit=1000, used_traffic=900),
            User(id=3, username="carol", key="k3", services=[service]),
        ])
        db.commit()

    limited = _Node(1, [_stat(1, 200), _stat(2, 200), _stat(999, 50)])
    unlimited = _Node(0, [_stat(3, 500)])
    nodes.register(7, limited)
    nodes.register(8, unlimited)

    writers = []
    real_store = record_usages.store_usages

    def store(api_params, coefficients):
        writers.append(threading.get_ident())
        return real_store(api_params, coefficients)

    monkeypatch.setattr(record_usages, "store_usages", store)

    loop_thread = _run_tick()

    # База писалась не из loop.
    assert writers and writers[0] != loop_thread

    with Session(engine) as db:
        users = {
            name: (used, lifetime)
            for name, used, lifetime in db.execute(
                select(
                    User.username, User.used_traffic,
                    User.lifetime_used_traffic,
                )
            )
        }
        logs = {
            (r.node_id, r.user_id): r.used_traffic
            for r in db.scalars(select(NodeUserUsage))
        }
        node_down = {
            r.node_id: r.downlink for r in db.scalars(select(NodeUsage))
        }
    assert users == {
        "alice": (900, 200),
        "bob": (1100, 200),
        "carol": (0, 0),
    }
    assert logs == {(7, 1): 200, (7, 2): 200, (8, 3): 0}
    # Нода считает свой трафик целиком, без коэффициента и без чужих uid.
    assert node_down == {7: 400, 8: 500}
    assert set(node_traffic_monitor._last_traffic_ts) == {7, 8}

    # Уведомления ушли из loop, в прежнем порядке.
    assert [(t, a, u.username) for t, a, u in loop_calls] == [
        (loop_thread, UserNotification.Action.reached_usage_percent, "alice"),
        (loop_thread, UserNotification.Action.data_limit_exhausted, "bob"),
    ]
    assert loop_calls[0][2].used_traffic == 900

    # bob снят с лимитной ноды тоже из loop; безлимитную это не касается.
    assert len(limited.updates) == 1
    pushed_from, update = limited.updates[0]
    assert pushed_from == loop_thread
    assert update["user"].username == "bob"
    assert update["inbounds"] == []
    assert unlimited.updates == []


def test_quiet_tick_sends_nothing(engine, nodes, loop_calls):
    """Нода молчит: в базу ничего, на ноды и в уведомления тоже."""
    quiet = _Node(1)
    nodes.register(7, quiet)

    _run_tick()

    with Session(engine) as db:
        assert db.scalars(select(NodeUserUsage)).all() == []
    assert quiet.updates == []
    assert loop_calls == []
