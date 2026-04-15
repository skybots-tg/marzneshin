"""Aggregate old hourly traffic records into daily summaries and purge expired data.

Runs once a day:
  1. SUM hourly rows older than USAGE_RETENTION_DAYS into daily rows (per user/node)
  2. DELETE the hourly originals
  3. DELETE daily rows older than USAGE_MAX_RETENTION_DAYS (default 180 days)
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import and_, cast, Date, delete, func, insert, select

from app.db import GetDB
from app.db.models import (
    NodeUsage,
    NodeUserUsage,
)
from app.db.models.proxy import NodeUsageDaily, NodeUserUsageDaily
from app.core.settings import settings

logger = logging.getLogger(__name__)

BATCH_SIZE = 5000


def _aggregate_node_user_usages(db, cutoff: datetime) -> int:
    """Aggregate node_user_usages rows older than cutoff into daily table."""
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
    """Aggregate node_usages rows older than cutoff into daily table."""
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


def _purge_old_daily_data(db, max_cutoff_date) -> tuple[int, int]:
    """Delete daily records older than max_cutoff_date."""
    user_purged = db.execute(
        delete(NodeUserUsageDaily).where(NodeUserUsageDaily.date < max_cutoff_date)
    ).rowcount

    node_purged = db.execute(
        delete(NodeUsageDaily).where(NodeUsageDaily.date < max_cutoff_date)
    ).rowcount

    return user_purged, node_purged


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
    max_cutoff = (today - timedelta(days=max_retention_days)).date()

    logger.info(
        f"Aggregating hourly records older than {cutoff.date()} "
        f"(retention={retention_days}d), "
        f"purging daily records older than {max_cutoff} "
        f"(max_retention={max_retention_days}d)"
    )

    with GetDB() as db:
        user_deleted = _aggregate_node_user_usages(db, cutoff)
        db.commit()

        node_deleted = _aggregate_node_usages(db, cutoff)
        db.commit()

        user_purged, node_purged = _purge_old_daily_data(db, max_cutoff)
        db.commit()

    logger.info(
        f"Aggregation complete: {user_deleted} node_user_usages + "
        f"{node_deleted} node_usages rows compressed into daily summaries; "
        f"purged {user_purged} + {node_purged} daily rows older than {max_cutoff}"
    )
