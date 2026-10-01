"""Aggregate old traffic records into coarser time buckets.

Runs once a day (03:00 UTC by default). Retention tiers for node / user
traffic (each tier lives in its own table, queried transparently by the
read paths in ``app.db.crud.user`` / ``app.db.crud.node``):

    hourly   node_user_usages          last USAGE_RETENTION_DAYS days   (30d)
      -> daily     node_user_usages_daily      up to USAGE_MAX_RETENTION_DAYS (180d)
        -> biweekly  node_user_usages_biweekly   older than 180d (retained)

So the most recent 30 days stay hour-by-hour, 30d–6mo collapse to one row
per day, and everything past ~6 months collapses to one row per fixed
2-week period and is kept indefinitely (instead of being purged as before).

Steps each run:
  1. node_user_usages hourly → daily   (older than USAGE_RETENTION_DAYS)
  2. node_usages hourly → daily
  3. node_user_usages_daily → biweekly (older than USAGE_MAX_RETENTION_DAYS)
  4. node_usages_daily → biweekly
  5. user_device_traffic 5-min → daily  (older than 7 days)
  6. user_device_traffic_daily → weekly  (older than 90 days)

How a run executes. The old version ran every query straight on the event
loop and froze the whole API for ~20 s each night, long enough for the
central backend's subscription requests to time out:

* The scheduler coroutine only hands the work to a worker thread
  (``asyncio.to_thread``). All queries here are synchronous SQLAlchemy and
  must never run on the event loop.
* Each step walks its source table oldest-first in slices of about
  ``SLICE_ROWS`` rows. A slice is aggregated, upserted into the coarser
  table and deleted in ONE short transaction, so locks cover a few
  thousand old rows at a time, every statement stays far below
  ``max_statement_time``, and a crash or a retry can never count the same
  traffic twice.
* Between slices the thread pauses briefly so the purge does not hog the
  disk while live traffic is being recorded.

Nothing else writes rows older than the cutoffs (live recording only
touches the current hour / 5-min bucket), so reading a slice and deleting
it in the same transaction sees the same set of rows.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, date as date_type, timedelta
from typing import Callable

from sqlalchemy import Date, DateTime, and_, delete, func, select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import OperationalError

from app.db import GetDB
from app.db.models import NodeUsage, NodeUserUsage
from app.db.models.device import (
    UserDeviceTraffic,
    UserDeviceTrafficDaily,
    UserDeviceTrafficWeekly,
)
from app.db.models.proxy import (
    NodeUsageDaily,
    NodeUsageBiweekly,
    NodeUserUsageDaily,
    NodeUserUsageBiweekly,
)
from app.core.settings import settings
from app.utils.usage_buckets import biweek_start

logger = logging.getLogger(__name__)

# Source rows per transaction. Rows sharing one timestamp are never split,
# so a slice can exceed this by at most one bucket (~1k rows for device
# traffic, a few hundred for hourly usage).
SLICE_ROWS = 5000
# Rows per multi-row upsert statement (keeps bind parameters well below the
# SQLite / MySQL placeholder limits).
UPSERT_CHUNK = 500
# Pause between slices, seconds.
SLICE_PAUSE = 0.05
SLICE_ATTEMPTS = 3

DEVICE_TRAFFIC_DAILY_CUTOFF_DAYS = 7
DEVICE_TRAFFIC_WEEKLY_CUTOFF_DAYS = 90


def _monday_of(d: date_type) -> date_type:
    """Return the Monday of the week containing date d."""
    return d - timedelta(days=d.weekday())


def _same_day(d: date_type) -> date_type:
    return d


@dataclass(frozen=True)
class _Step:
    """One tier transition: ``source`` rows → ``target`` buckets."""

    source: type
    time_col: str
    target: type
    bucket_col: str
    bucket: Callable[[date_type], date_type]  # calendar day -> bucket start
    keys: tuple[str, ...]  # identity columns copied to the target
    conflict: tuple[str, ...]  # the target's unique key
    sums: tuple[str, ...]  # additive counters

    @property
    def name(self) -> str:
        return (
            f"{self.source.__tablename__} → {self.target.__tablename__}"
        )


NODE_USER_TO_DAILY = _Step(
    NodeUserUsage, "created_at", NodeUserUsageDaily, "date", _same_day,
    keys=("user_id", "node_id"),
    conflict=("date", "user_id", "node_id"),
    sums=("used_traffic",),
)
NODE_TO_DAILY = _Step(
    NodeUsage, "created_at", NodeUsageDaily, "date", _same_day,
    keys=("node_id",),
    conflict=("date", "node_id"),
    sums=("uplink", "downlink"),
)
NODE_USER_DAILY_TO_BIWEEKLY = _Step(
    NodeUserUsageDaily, "date", NodeUserUsageBiweekly, "period_start",
    biweek_start,
    keys=("user_id", "node_id"),
    conflict=("period_start", "user_id", "node_id"),
    sums=("used_traffic",),
)
NODE_DAILY_TO_BIWEEKLY = _Step(
    NodeUsageDaily, "date", NodeUsageBiweekly, "period_start", biweek_start,
    keys=("node_id",),
    conflict=("period_start", "node_id"),
    sums=("uplink", "downlink"),
)
DEVICE_TO_DAILY = _Step(
    UserDeviceTraffic, "bucket_start", UserDeviceTrafficDaily, "date",
    _same_day,
    keys=("device_id", "user_id", "node_id"),
    conflict=("device_id", "node_id", "date"),
    sums=("upload_bytes", "download_bytes", "connect_count"),
)
DEVICE_DAILY_TO_WEEKLY = _Step(
    UserDeviceTrafficDaily, "date", UserDeviceTrafficWeekly, "week_start",
    _monday_of,
    keys=("device_id", "user_id", "node_id"),
    conflict=("device_id", "node_id", "week_start"),
    sums=("upload_bytes", "download_bytes", "connect_count"),
)


# ============================================================================
# One slice: aggregate → upsert → delete, in a single transaction
# ============================================================================

def _slice_end(db, col, start, cutoff):
    """Exclusive upper bound of the slice that begins at ``start``.

    It is the timestamp of the ``SLICE_ROWS``-th row after ``start``, so
    rows sharing a timestamp always land in the same slice and the
    ``>= start AND < end`` range is exact for both the read and the delete.
    Gaps in the data are skipped for free.
    """
    end = db.execute(
        select(col)
        .where(and_(col >= start, col < cutoff))
        .order_by(col)
        .offset(SLICE_ROWS)
        .limit(1)
    ).scalar()
    if end is not None and end == start:
        # One timestamp holds more than SLICE_ROWS rows: take it whole.
        end = db.execute(
            select(func.min(col)).where(and_(col > start, col < cutoff))
        ).scalar()
    return cutoff if end is None else end


def _upsert(db, step: _Step, rows: list[dict]) -> None:
    """Add ``rows`` to the target table, summing into existing buckets."""
    table = step.target.__table__
    dialect = db.get_bind().dialect.name
    if dialect in ("mysql", "mariadb"):
        stmt = mysql_insert(table).values(rows)
        stmt = stmt.on_duplicate_key_update(
            {s: table.c[s] + stmt.inserted[s] for s in step.sums}
        )
    elif dialect in ("sqlite", "postgresql"):
        insert = sqlite_insert if dialect == "sqlite" else pg_insert
        stmt = insert(table).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=list(step.conflict),
            set_={s: table.c[s] + stmt.excluded[s] for s in step.sums},
        )
    else:
        raise NotImplementedError(f"upsert is not supported on {dialect}")
    db.execute(stmt)


def _compress_slice(db, step: _Step, start, end) -> tuple[int, int]:
    """Move the source rows in ``[start, end)`` into the target tier.

    Returns (target rows upserted, source rows deleted). Does not commit.
    """
    src = step.source
    time_col = getattr(src, step.time_col)
    day = (
        func.date(time_col, type_=Date)
        if isinstance(time_col.type, DateTime)
        else time_col
    )
    keys = [getattr(src, k) for k in step.keys]
    in_slice = and_(time_col >= start, time_col < end)

    rows = db.execute(
        select(
            day.label("day"),
            *keys,
            *[
                func.coalesce(func.sum(getattr(src, s)), 0).label(s)
                for s in step.sums
            ],
        )
        .where(in_slice)
        .group_by(day, *keys)
    ).all()

    # Several days fold into one bi-weekly / weekly bucket, so the final
    # grouping happens here; keyed by the target's unique key so a single
    # statement never hits the same target row twice.
    buckets: dict[tuple, dict] = {}
    for row in rows:
        values = {step.bucket_col: step.bucket(row.day)}
        values.update((k, getattr(row, k)) for k in step.keys)
        ident = tuple(values[c] for c in step.conflict)
        acc = buckets.get(ident)
        if acc is None:
            acc = buckets[ident] = {**values, **{s: 0 for s in step.sums}}
        for s in step.sums:
            acc[s] += int(getattr(row, s) or 0)

    out = list(buckets.values())
    for i in range(0, len(out), UPSERT_CHUNK):
        _upsert(db, step, out[i:i + UPSERT_CHUNK])

    deleted = db.execute(
        delete(src).where(in_slice),
        execution_options={"synchronize_session": False},
    ).rowcount
    return len(out), deleted


def _run_slice(step: _Step, start, cutoff) -> tuple:
    """Compress one slice in its own transaction, retrying transient errors
    (deadlocks, lock waits, MariaDB 1020 under snapshot isolation).

    Returns (slice end, rows upserted, rows deleted).
    """
    time_col = getattr(step.source, step.time_col)
    for attempt in range(1, SLICE_ATTEMPTS + 1):
        try:
            with GetDB() as db:
                end = _slice_end(db, time_col, start, cutoff)
                upserted, deleted = _compress_slice(db, step, start, end)
                db.commit()
                return end, upserted, deleted
        except OperationalError as e:
            if attempt == SLICE_ATTEMPTS:
                raise
            logger.warning(
                "%s: slice from %s, retry %d after error: %s",
                step.name, start, attempt, e,
            )
            time.sleep(0.5 * attempt)


def compress_older_than(step: _Step, cutoff) -> tuple[int, int, int]:
    """Move every ``step.source`` row older than ``cutoff`` into the target
    tier, slice by slice. Returns (slices, rows upserted, rows deleted)."""
    time_col = getattr(step.source, step.time_col)
    with GetDB() as db:
        start = db.execute(
            select(func.min(time_col)).where(time_col < cutoff)
        ).scalar()

    slices = upserted = deleted = 0
    while start is not None and start < cutoff:
        start, up, dl = _run_slice(step, start, cutoff)
        if up or dl:
            slices += 1
            upserted += up
            deleted += dl
            time.sleep(SLICE_PAUSE)
    return slices, upserted, deleted


# ============================================================================
# Main entry point
# ============================================================================

def run_aggregation(today: datetime | None = None) -> None:
    """Run every tier transition. Blocking — call from a worker thread."""
    retention_days = settings.tasks.usage_retention_days
    max_retention_days = settings.tasks.usage_max_retention_days

    if retention_days <= 0:
        logger.info("Usage aggregation disabled (retention_days <= 0)")
        return

    if today is None:
        today = datetime.utcnow()
    today = today.replace(hour=0, minute=0, second=0, microsecond=0)

    plan = [
        (NODE_USER_TO_DAILY, today - timedelta(days=retention_days)),
        (NODE_TO_DAILY, today - timedelta(days=retention_days)),
        (
            NODE_USER_DAILY_TO_BIWEEKLY,
            (today - timedelta(days=max_retention_days)).date(),
        ),
        (
            NODE_DAILY_TO_BIWEEKLY,
            (today - timedelta(days=max_retention_days)).date(),
        ),
        (
            DEVICE_TO_DAILY,
            today - timedelta(days=DEVICE_TRAFFIC_DAILY_CUTOFF_DAYS),
        ),
        (
            DEVICE_DAILY_TO_WEEKLY,
            (today - timedelta(days=DEVICE_TRAFFIC_WEEKLY_CUTOFF_DAYS)).date(),
        ),
    ]

    logger.info(
        f"Aggregating: hourly→daily (>{retention_days}d), "
        f"daily→biweekly (>{max_retention_days}d), "
        f"device 5min→daily (>{DEVICE_TRAFFIC_DAILY_CUTOFF_DAYS}d), "
        f"device daily→weekly (>{DEVICE_TRAFFIC_WEEKLY_CUTOFF_DAYS}d)"
    )

    run_started = time.monotonic()
    for step, cutoff in plan:
        started = time.monotonic()
        try:
            slices, upserted, deleted = compress_older_than(step, cutoff)
        except Exception:
            # Steps are independent; a failed one is retried in full next
            # night, and committed slices are already consistent.
            logger.exception("%s: aggregation failed", step.name)
            continue
        logger.info(
            "%s: %d rows → %d rows in %d slices, %.1fs (cutoff %s)",
            step.name, deleted, upserted, slices,
            time.monotonic() - started,
            cutoff.date() if isinstance(cutoff, datetime) else cutoff,
        )

    logger.info(
        "Usage aggregation finished in %.1fs", time.monotonic() - run_started
    )


async def aggregate_old_usages():
    """Scheduler entry point.

    The work is blocking database I/O; it runs in a worker thread so the
    event loop keeps serving API requests while old rows are compressed.
    """
    await asyncio.to_thread(run_aggregation)
