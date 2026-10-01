"""Ночное сжатие трафика не должно останавливать панель.

Раньше ``aggregate_old_usages`` гоняла все запросы прямо в event loop:
каждую ночь в 03:00 API молчал ~20 секунд, central_server ловил ReadTimeout
на ``get_user`` и отдавал клиентам 500 вместо подписки. Теперь работа идёт
в отдельном потоке, кусками по ``SLICE_ROWS`` строк, и каждый кусок
(свернуть → дописать в грубую таблицу → удалить исходники) — одна короткая
транзакция. Тесты проверяют, что нарезка на куски не теряет и не удваивает
трафик и что сбой посреди куска откатывает его целиком.
"""

import asyncio
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import BigInteger, create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import NodeUsage, NodeUserUsage
from app.db.models.device import (
    UserDeviceTraffic,
    UserDeviceTrafficDaily,
    UserDeviceTrafficWeekly,
)
from app.db.models.proxy import (
    NodeUsageBiweekly,
    NodeUsageDaily,
    NodeUserUsageBiweekly,
    NodeUserUsageDaily,
)
from app.tasks import aggregate_usages as agg
from app.utils.usage_buckets import biweek_start



@compiles(BigInteger, "sqlite")
def _bigint_as_rowid(type_, compiler, **kw):
    # SQLite автоинкрементит только INTEGER PRIMARY KEY, а у таблиц
    # трафика устройств id — BIGINT. На MariaDB это ничего не меняет.
    return "INTEGER"


_TABLES = [
    m.__table__
    for m in (
        NodeUserUsage, NodeUserUsageDaily, NodeUserUsageBiweekly,
        NodeUsage, NodeUsageDaily, NodeUsageBiweekly,
        UserDeviceTraffic, UserDeviceTrafficDaily, UserDeviceTrafficWeekly,
    )
]

TODAY = datetime(2026, 10, 1, 3, 0)


@pytest.fixture
def engine(monkeypatch):
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng, tables=_TABLES)

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

    monkeypatch.setattr(agg, "GetDB", get_db)
    monkeypatch.setattr(agg, "SLICE_PAUSE", 0)
    yield eng
    eng.dispose()


def _add(eng, *rows):
    with Session(eng) as db:
        db.add_all(rows)
        db.commit()


def _all(eng, model, *order):
    with Session(eng) as db:
        return db.execute(select(model).order_by(*order)).scalars().all()


def _hourly(eng, start, hours, users=(1, 2), node=7, traffic=10):
    _add(eng, *[
        NodeUserUsage(
            created_at=start + timedelta(hours=h),
            user_id=u, node_id=node, used_traffic=traffic,
        )
        for h in range(hours)
        for u in users
    ])


@pytest.mark.parametrize("slice_rows", [1, 3, 5000])
def test_hourly_to_daily_is_exact_for_any_slice_size(
    engine, monkeypatch, slice_rows
):
    monkeypatch.setattr(agg, "SLICE_ROWS", slice_rows)
    cutoff = datetime(2026, 9, 1)
    # Two full old days, plus a day that must stay hourly.
    _hourly(engine, datetime(2026, 8, 30), 48)
    _hourly(engine, cutoff, 24)
    # Yesterday's run already left a partial day: it must be summed into.
    _add(engine, NodeUserUsageDaily(
        date=date(2026, 8, 30), user_id=1, node_id=7, used_traffic=1000,
    ))

    slices, upserted, deleted = agg.compress_older_than(
        agg.NODE_USER_TO_DAILY, cutoff
    )

    assert deleted == 96
    assert (slices == 1) == (slice_rows == 5000)
    daily = {
        (r.date, r.user_id): r.used_traffic
        for r in _all(engine, NodeUserUsageDaily, NodeUserUsageDaily.id)
    }
    assert daily == {
        (date(2026, 8, 30), 1): 1240,
        (date(2026, 8, 30), 2): 240,
        (date(2026, 8, 31), 1): 240,
        (date(2026, 8, 31), 2): 240,
    }
    left = _all(engine, NodeUserUsage, NodeUserUsage.id)
    assert len(left) == 48
    assert min(r.created_at for r in left) == cutoff


def test_one_timestamp_bigger_than_a_slice_is_taken_whole(
    engine, monkeypatch
):
    """В одном 5-минутном бакете бывает больше строк, чем в куске:
    его нельзя резать, иначе удаление по диапазону зацепит лишнее."""
    monkeypatch.setattr(agg, "SLICE_ROWS", 2)
    bucket = datetime(2026, 9, 20, 12, 5)
    _add(engine, *[
        UserDeviceTraffic(
            device_id=d, user_id=1, node_id=3, bucket_start=bucket,
            upload_bytes=1, download_bytes=2, connect_count=1,
        )
        for d in range(1, 6)
    ])

    slices, upserted, deleted = agg.compress_older_than(
        agg.DEVICE_TO_DAILY, datetime(2026, 9, 24)
    )

    assert (slices, upserted, deleted) == (1, 5, 5)
    daily = _all(engine, UserDeviceTrafficDaily, UserDeviceTrafficDaily.device_id)
    assert [(r.device_id, r.date, r.download_bytes) for r in daily] == [
        (d, date(2026, 9, 20), 2) for d in range(1, 6)
    ]
    assert _all(engine, UserDeviceTraffic) == []


def test_device_traffic_across_slices_sums_into_one_daily_row(
    engine, monkeypatch
):
    monkeypatch.setattr(agg, "SLICE_ROWS", 3)
    day = datetime(2026, 9, 20)
    _add(engine, *[
        UserDeviceTraffic(
            device_id=9, user_id=4, node_id=3,
            bucket_start=day + timedelta(minutes=5 * i),
            upload_bytes=100, download_bytes=1000, connect_count=2,
        )
        for i in range(288)
    ])

    agg.compress_older_than(agg.DEVICE_TO_DAILY, datetime(2026, 9, 24))

    (row,) = _all(engine, UserDeviceTrafficDaily)
    assert (row.date, row.user_id, row.upload_bytes, row.download_bytes,
            row.connect_count) == (date(2026, 9, 20), 4, 28800, 288000, 576)


def test_daily_rows_fold_into_biweekly_and_weekly_buckets(engine):
    first = date(2026, 3, 2)  # Monday
    _add(engine, *[
        NodeUserUsageDaily(
            date=first + timedelta(days=i), user_id=1, node_id=7,
            used_traffic=5,
        )
        for i in range(28)
    ], NodeUserUsageBiweekly(
        period_start=biweek_start(first), user_id=1, node_id=7,
        used_traffic=1,
    ))
    _add(engine, *[
        UserDeviceTrafficDaily(
            device_id=9, user_id=4, node_id=3, date=first + timedelta(days=i),
            upload_bytes=1, download_bytes=1, connect_count=1,
        )
        for i in range(14)
    ])

    agg.compress_older_than(agg.NODE_USER_DAILY_TO_BIWEEKLY, date(2026, 4, 4))
    agg.compress_older_than(agg.DEVICE_DAILY_TO_WEEKLY, date(2026, 7, 3))

    biweekly = {
        r.period_start: r.used_traffic
        for r in _all(engine, NodeUserUsageBiweekly)
    }
    assert sum(biweekly.values()) == 28 * 5 + 1
    assert all(biweek_start(d) == d for d in biweekly)
    assert _all(engine, NodeUserUsageDaily) == []

    weekly = _all(engine, UserDeviceTrafficWeekly, UserDeviceTrafficWeekly.week_start)
    assert [(r.week_start, r.connect_count) for r in weekly] == [
        (first, 7), (first + timedelta(days=7), 7),
    ]


def test_failed_slice_is_rolled_back_and_retried_without_double_count(
    engine, monkeypatch
):
    monkeypatch.setattr(agg, "SLICE_ROWS", 4)
    _hourly(engine, datetime(2026, 8, 30), 6)

    real = agg._compress_slice
    calls = {"n": 0}

    def flaky(db, step, start, end):
        result = real(db, step, start, end)  # upsert + delete already ran
        calls["n"] += 1
        if calls["n"] == 2:
            raise OperationalError("DELETE", {}, Exception("1020"))
        return result

    monkeypatch.setattr(agg, "_compress_slice", flaky)

    agg.compress_older_than(agg.NODE_USER_TO_DAILY, datetime(2026, 9, 1))

    daily = _all(engine, NodeUserUsageDaily, NodeUserUsageDaily.user_id)
    assert [r.used_traffic for r in daily] == [60, 60]
    assert _all(engine, NodeUserUsage) == []


def test_full_run_moves_every_tier(engine):
    _hourly(engine, datetime(2026, 8, 1), 3)
    _add(
        engine,
        NodeUsage(
            created_at=datetime(2026, 8, 1, 5), node_id=7,
            uplink=1, downlink=2,
        ),
        NodeUsageDaily(
            date=date(2026, 3, 1), node_id=7, uplink=3, downlink=4,
        ),
        UserDeviceTraffic(
            device_id=9, user_id=4, node_id=3,
            bucket_start=datetime(2026, 9, 1, 0, 5),
            upload_bytes=1, download_bytes=1, connect_count=1,
        ),
        *[
            UserDeviceTrafficDaily(
                device_id=9, user_id=4, node_id=3, date=d,
                upload_bytes=1, download_bytes=1, connect_count=1,
            )
            for d in (date(2026, 6, 3), date(2026, 8, 1))
        ],
    )

    agg.run_aggregation(today=TODAY)

    assert _all(engine, NodeUserUsage) == []
    assert _all(engine, NodeUsage) == []
    assert _all(engine, UserDeviceTraffic) == []
    assert len(_all(engine, NodeUserUsageDaily)) == 2
    assert [r.date for r in _all(engine, NodeUsageDaily)] == [date(2026, 8, 1)]
    assert len(_all(engine, NodeUsageBiweekly)) == 1
    # Порог недельного яруса — 90 дней (2026-07-03): 06-03 уходит в неделю,
    # 08-01 и только что свёрнутый 09-01 остаются днями.
    assert sorted(r.date for r in _all(engine, UserDeviceTrafficDaily)) == [
        date(2026, 8, 1), date(2026, 9, 1),
    ]
    assert [r.week_start for r in _all(engine, UserDeviceTrafficWeekly)] == [
        date(2026, 6, 1),
    ]


def test_scheduler_job_leaves_the_event_loop_free(monkeypatch):
    """Регрессия на сам инцидент: пока идёт сжатие, loop отвечает."""
    monkeypatch.setattr(agg, "run_aggregation", lambda: time.sleep(0.5))

    async def scenario():
        ticks = 0

        async def heartbeat():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.02)
                ticks += 1

        beat = asyncio.create_task(heartbeat())
        await agg.aggregate_old_usages()
        beat.cancel()
        return ticks

    assert asyncio.run(scenario()) >= 10
