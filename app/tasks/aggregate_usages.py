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
"""

import logging
import time
from datetime import datetime, date as date_type, timedelta

from sqlalchemy import and_, cast, Date, delete, func, insert, select, text, column
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

BATCH_SIZE = 5000
DEVICE_TRAFFIC_DAILY_CUTOFF_DAYS = 7
DEVICE_TRAFFIC_WEEKLY_CUTOFF_DAYS = 90


# ============================================================================
# Node / NodeUser usage aggregation (existing logic)
# ============================================================================

def _aggregate_node_user_usages(db, cutoff: datetime) -> int:
    agg_query = (
        select(
            cast(NodeUserUsage.created_at, Date).label("date"),
            NodeUserUsage.user_id,
            NodeUserUsage.node_id,
            func.sum(NodeUserUsage.used_traffic).label("used_traffic"),
        )
        .where(NodeUserUsage.created_at < cutoff)
        .group_by(
            cast(NodeUserUsage.created_at, Date),
            NodeUserUsage.user_id,
            NodeUserUsage.node_id,
        )
    )

    rows = db.execute(agg_query).fetchall()
    if not rows:
        return 0

    for row in rows:
        existing = db.execute(
            select(NodeUserUsageDaily.id).where(
                and_(
                    NodeUserUsageDaily.date == row.date,
                    NodeUserUsageDaily.user_id == row.user_id,
                    NodeUserUsageDaily.node_id == row.node_id,
                )
            )
        ).first()

        if existing:
            db.execute(
                NodeUserUsageDaily.__table__.update()
                .where(NodeUserUsageDaily.id == existing.id)
                .values(
                    used_traffic=NodeUserUsageDaily.used_traffic + row.used_traffic
                )
            )
        else:
            db.execute(
                insert(NodeUserUsageDaily).values(
                    date=row.date,
                    user_id=row.user_id,
                    node_id=row.node_id,
                    used_traffic=row.used_traffic,
                )
            )

    deleted = db.execute(
        delete(NodeUserUsage).where(NodeUserUsage.created_at < cutoff)
    ).rowcount

    return deleted


def _aggregate_node_usages(db, cutoff: datetime) -> int:
    agg_query = (
        select(
            cast(NodeUsage.created_at, Date).label("date"),
            NodeUsage.node_id,
            func.sum(NodeUsage.uplink).label("uplink"),
            func.sum(NodeUsage.downlink).label("downlink"),
        )
        .where(NodeUsage.created_at < cutoff)
        .group_by(
            cast(NodeUsage.created_at, Date),
            NodeUsage.node_id,
        )
    )

    rows = db.execute(agg_query).fetchall()
    if not rows:
        return 0

    for row in rows:
        existing = db.execute(
            select(NodeUsageDaily.id).where(
                and_(
                    NodeUsageDaily.date == row.date,
                    NodeUsageDaily.node_id == row.node_id,
                )
            )
        ).first()

        if existing:
            db.execute(
                NodeUsageDaily.__table__.update()
                .where(NodeUsageDaily.id == existing.id)
                .values(
                    uplink=NodeUsageDaily.uplink + row.uplink,
                    downlink=NodeUsageDaily.downlink + row.downlink,
                )
            )
        else:
            db.execute(
                insert(NodeUsageDaily).values(
                    date=row.date,
                    node_id=row.node_id,
                    uplink=row.uplink,
                    downlink=row.downlink,
                )
            )

    deleted = db.execute(
        delete(NodeUsage).where(NodeUsage.created_at < cutoff)
    ).rowcount

    return deleted


def _aggregate_node_user_daily_to_biweekly(db, cutoff_date) -> int:
    """Compress per-user daily rows older than ``cutoff_date`` into fixed
    2-week buckets, then delete the consumed daily rows.

    Returns the number of daily rows removed.
    """
    old_rows = db.execute(
        select(
            NodeUserUsageDaily.date,
            NodeUserUsageDaily.user_id,
            NodeUserUsageDaily.node_id,
            NodeUserUsageDaily.used_traffic,
        ).where(NodeUserUsageDaily.date < cutoff_date)
    ).fetchall()

    if not old_rows:
        return 0

    buckets: dict[tuple, int] = {}
    for row in old_rows:
        key = (biweek_start(row.date), row.user_id, row.node_id)
        buckets[key] = buckets.get(key, 0) + (row.used_traffic or 0)

    for (period_start, user_id, node_id), used_traffic in buckets.items():
        existing = db.execute(
            select(NodeUserUsageBiweekly.id).where(
                and_(
                    NodeUserUsageBiweekly.period_start == period_start,
                    NodeUserUsageBiweekly.user_id == user_id,
                    NodeUserUsageBiweekly.node_id == node_id,
                )
            )
        ).first()

        if existing:
            db.execute(
                NodeUserUsageBiweekly.__table__.update()
                .where(NodeUserUsageBiweekly.id == existing.id)
                .values(
                    used_traffic=NodeUserUsageBiweekly.used_traffic
                    + used_traffic
                )
            )
        else:
            db.execute(
                insert(NodeUserUsageBiweekly).values(
                    period_start=period_start,
                    user_id=user_id,
                    node_id=node_id,
                    used_traffic=used_traffic,
                )
            )

    deleted = db.execute(
        delete(NodeUserUsageDaily).where(NodeUserUsageDaily.date < cutoff_date)
    ).rowcount

    return deleted


def _aggregate_node_daily_to_biweekly(db, cutoff_date) -> int:
    """Compress per-node daily rows older than ``cutoff_date`` into fixed
    2-week buckets, then delete the consumed daily rows.

    Returns the number of daily rows removed.
    """
    old_rows = db.execute(
        select(
            NodeUsageDaily.date,
            NodeUsageDaily.node_id,
            NodeUsageDaily.uplink,
            NodeUsageDaily.downlink,
        ).where(NodeUsageDaily.date < cutoff_date)
    ).fetchall()

    if not old_rows:
        return 0

    buckets: dict[tuple, dict] = {}
    for row in old_rows:
        key = (biweek_start(row.date), row.node_id)
        agg = buckets.setdefault(key, {"uplink": 0, "downlink": 0})
        agg["uplink"] += row.uplink or 0
        agg["downlink"] += row.downlink or 0

    for (period_start, node_id), totals in buckets.items():
        existing = db.execute(
            select(NodeUsageBiweekly.id).where(
                and_(
                    NodeUsageBiweekly.period_start == period_start,
                    NodeUsageBiweekly.node_id == node_id,
                )
            )
        ).first()

        if existing:
            db.execute(
                NodeUsageBiweekly.__table__.update()
                .where(NodeUsageBiweekly.id == existing.id)
                .values(
                    uplink=NodeUsageBiweekly.uplink + totals["uplink"],
                    downlink=NodeUsageBiweekly.downlink + totals["downlink"],
                )
            )
        else:
            db.execute(
                insert(NodeUsageBiweekly).values(
                    period_start=period_start,
                    node_id=node_id,
                    uplink=totals["uplink"],
                    downlink=totals["downlink"],
                )
            )

    deleted = db.execute(
        delete(NodeUsageDaily).where(NodeUsageDaily.date < cutoff_date)
    ).rowcount

    return deleted


# ============================================================================
# Device traffic: 5-min → daily aggregation
# ============================================================================

def _aggregate_device_traffic_to_daily(db, cutoff: datetime) -> tuple[int, int]:
    """Aggregate user_device_traffic rows older than cutoff into daily table.

    Processes one calendar day at a time to stay within statement_timeout.
    Returns (rows_upserted, rows_deleted).
    """
    T = UserDeviceTraffic
    D = UserDeviceTrafficDaily

    oldest_row = db.execute(
        select(func.min(T.bucket_start)).where(T.bucket_start < cutoff)
    ).scalar()
    if oldest_row is None:
        return 0, 0

    total_upserted = 0
    total_deleted = 0
    current_day = oldest_row.date()
    cutoff_date = cutoff.date()

    while current_day < cutoff_date:
        next_day = current_day + timedelta(days=1)

        agg_query = (
            select(
                T.device_id, T.user_id, T.node_id,
                func.sum(T.upload_bytes).label("upload_bytes"),
                func.sum(T.download_bytes).label("download_bytes"),
                func.sum(T.connect_count).label("connect_count"),
            )
            .where(and_(
                T.bucket_start >= datetime(current_day.year, current_day.month, current_day.day),
                T.bucket_start < datetime(next_day.year, next_day.month, next_day.day),
            ))
            .group_by(T.device_id, T.user_id, T.node_id)
        )

        rows = db.execute(agg_query).fetchall()
        if not rows:
            current_day = next_day
            continue

        for attempt in range(3):
            try:
                for row in rows:
                    existing = db.execute(
                        select(D.id).where(and_(
                            D.device_id == row.device_id,
                            D.node_id == row.node_id,
                            D.date == current_day,
                        ))
                    ).first()

                    if existing:
                        db.execute(
                            D.__table__.update()
                            .where(D.id == existing.id)
                            .values(
                                upload_bytes=D.upload_bytes + row.upload_bytes,
                                download_bytes=D.download_bytes + row.download_bytes,
                                connect_count=D.connect_count + row.connect_count,
                            )
                        )
                    else:
                        db.execute(insert(D).values(
                            device_id=row.device_id,
                            user_id=row.user_id,
                            node_id=row.node_id,
                            date=current_day,
                            upload_bytes=row.upload_bytes,
                            download_bytes=row.download_bytes,
                            connect_count=row.connect_count,
                        ))
                    total_upserted += 1
                db.commit()
                break
            except OperationalError as e:
                db.rollback()
                if attempt < 2:
                    logger.warning(f"  day {current_day}: retry {attempt+1} after error: {e}")
                    time.sleep(0.3 * (attempt + 1))
                else:
                    raise

        day_start = datetime(current_day.year, current_day.month, current_day.day)
        day_end = datetime(next_day.year, next_day.month, next_day.day)
        while True:
            result = db.execute(
                text(
                    "DELETE FROM user_device_traffic "
                    "WHERE bucket_start >= :d0 AND bucket_start < :d1 "
                    "LIMIT :batch"
                ),
                {"d0": day_start, "d1": day_end, "batch": BATCH_SIZE},
            )
            deleted = result.rowcount
            db.commit()
            total_deleted += deleted
            if deleted < BATCH_SIZE:
                break

        logger.info(
            f"  day {current_day}: {len(rows)} daily rows, deleted 5-min originals"
        )
        current_day = next_day

    return total_upserted, total_deleted


# ============================================================================
# Device traffic: daily → weekly aggregation
# ============================================================================

def _monday_of(d: date_type) -> date_type:
    """Return the Monday of the week containing date d."""
    return d - timedelta(days=d.weekday())


def _aggregate_device_traffic_to_weekly(db, cutoff_date: date_type) -> tuple[int, int]:
    """Aggregate user_device_traffic_daily rows older than cutoff into weekly.

    Returns (rows_inserted_or_updated, rows_deleted).
    """
    D = UserDeviceTrafficDaily
    W = UserDeviceTrafficWeekly

    old_rows = db.execute(
        select(
            D.device_id, D.user_id, D.node_id, D.date,
            D.upload_bytes, D.download_bytes, D.connect_count,
        ).where(D.date < cutoff_date)
    ).fetchall()

    if not old_rows:
        return 0, 0

    weekly_buckets: dict[tuple, dict] = {}
    for row in old_rows:
        week_start = _monday_of(row.date)
        key = (row.device_id, row.user_id, row.node_id, week_start)
        if key not in weekly_buckets:
            weekly_buckets[key] = {"upload": 0, "download": 0, "connects": 0}
        weekly_buckets[key]["upload"] += row.upload_bytes
        weekly_buckets[key]["download"] += row.download_bytes
        weekly_buckets[key]["connects"] += row.connect_count

    upserted = 0
    for (device_id, user_id, node_id, week_start), totals in weekly_buckets.items():
        existing = db.execute(
            select(W.id).where(
                and_(
                    W.device_id == device_id,
                    W.node_id == node_id,
                    W.week_start == week_start,
                )
            )
        ).first()

        if existing:
            db.execute(
                W.__table__.update()
                .where(W.id == existing.id)
                .values(
                    upload_bytes=W.upload_bytes + totals["upload"],
                    download_bytes=W.download_bytes + totals["download"],
                    connect_count=W.connect_count + totals["connects"],
                )
            )
        else:
            db.execute(
                insert(W).values(
                    device_id=device_id,
                    user_id=user_id,
                    node_id=node_id,
                    week_start=week_start,
                    upload_bytes=totals["upload"],
                    download_bytes=totals["download"],
                    connect_count=totals["connects"],
                )
            )
        upserted += 1

    deleted = db.execute(
        delete(D).where(D.date < cutoff_date)
    ).rowcount
    db.commit()

    return upserted, deleted


# ============================================================================
# Main entry point
# ============================================================================

async def aggregate_old_usages():
    """Main entry point called by the scheduler."""
    retention_days = settings.tasks.usage_retention_days
    max_retention_days = settings.tasks.usage_max_retention_days

    if retention_days <= 0:
        logger.info("Usage aggregation disabled (retention_days <= 0)")
        return

    today = datetime.utcnow().replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    cutoff = today - timedelta(days=retention_days)
    biweekly_cutoff = (today - timedelta(days=max_retention_days)).date()

    logger.info(
        f"Aggregating: hourly→daily (>{retention_days}d), "
        f"daily→biweekly (>{max_retention_days}d), "
        f"device 5min→daily (>{DEVICE_TRAFFIC_DAILY_CUTOFF_DAYS}d), "
        f"device daily→weekly (>{DEVICE_TRAFFIC_WEEKLY_CUTOFF_DAYS}d)"
    )

    with GetDB() as db:
        user_deleted = _aggregate_node_user_usages(db, cutoff)
        db.commit()

        node_deleted = _aggregate_node_usages(db, cutoff)
        db.commit()

        user_bw_deleted = _aggregate_node_user_daily_to_biweekly(
            db, biweekly_cutoff
        )
        db.commit()

        node_bw_deleted = _aggregate_node_daily_to_biweekly(db, biweekly_cutoff)
        db.commit()

    logger.info(
        f"Node usage: {user_deleted} hourly user + {node_deleted} hourly node "
        f"compressed to daily; {user_bw_deleted} user + {node_bw_deleted} node "
        f"daily rows compressed to biweekly (cutoff {biweekly_cutoff})"
    )

    device_daily_cutoff = today - timedelta(days=DEVICE_TRAFFIC_DAILY_CUTOFF_DAYS)
    device_weekly_cutoff = (today - timedelta(days=DEVICE_TRAFFIC_WEEKLY_CUTOFF_DAYS)).date()

    with GetDB() as db:
        d_upserted, d_deleted = _aggregate_device_traffic_to_daily(db, device_daily_cutoff)
        db.commit()

    logger.info(
        f"Device traffic 5min→daily: {d_upserted} daily rows upserted, "
        f"{d_deleted} 5-min rows removed (cutoff {device_daily_cutoff.date()})"
    )

    with GetDB() as db:
        w_upserted, w_deleted = _aggregate_device_traffic_to_weekly(db, device_weekly_cutoff)
        db.commit()

    logger.info(
        f"Device traffic daily→weekly: {w_upserted} weekly rows upserted, "
        f"{w_deleted} daily rows removed (cutoff {device_weekly_cutoff})"
    )
