from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional, Union

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.db.models import Node, NodeUserUsage
from app.db.models.proxy import NodeUserUsageDaily
from app.core.settings import settings
from app.models.node import NodeCreate, NodeModify, NodeStatus
from app.models.system import TrafficUsageSeries


def get_node(db: Session, name: str):
    return db.query(Node).filter(Node.name == name).first()


def get_node_by_id(db: Session, node_id: int):
    return db.query(Node).filter(Node.id == node_id).first()


def get_nodes(
    db: Session,
    status: Optional[Union[NodeStatus, list]] = None,
    enabled: bool = None,
):
    query = db.query(Node)

    if status:
        if isinstance(status, list):
            query = query.filter(Node.status.in_(status))
        else:
            query = query.filter(Node.status == status)

    if enabled:
        query = query.filter(Node.status != NodeStatus.disabled)

    return query.all()


def get_node_usage(
    db: Session, start: datetime, end: datetime, node: Node
) -> TrafficUsageSeries:
    usages = defaultdict(int)
    cutoff = datetime.utcnow().replace(
        hour=0, minute=0, second=0, microsecond=0
    ) - timedelta(days=settings.tasks.usage_retention_days)

    # Hourly data
    hourly_start = max(start, cutoff)
    if hourly_start < end:
        query = (
            db.query(
                NodeUserUsage.created_at, func.sum(NodeUserUsage.used_traffic)
            )
            .group_by(NodeUserUsage.created_at)
            .filter(
                and_(
                    NodeUserUsage.node_id == node.id,
                    NodeUserUsage.created_at >= hourly_start,
                    NodeUserUsage.created_at <= end,
                )
            )
        )
        for created_at, used_traffic in query.all():
            usages[created_at.replace(tzinfo=timezone.utc).timestamp()] += int(
                used_traffic
            )

    # Daily data
    if start < cutoff:
        daily_end = min(end, cutoff - timedelta(seconds=1))
        daily_query = (
            db.query(
                NodeUserUsageDaily.date,
                func.sum(NodeUserUsageDaily.used_traffic),
            )
            .group_by(NodeUserUsageDaily.date)
            .filter(
                and_(
                    NodeUserUsageDaily.node_id == node.id,
                    NodeUserUsageDaily.date >= start.date(),
                    NodeUserUsageDaily.date <= daily_end.date(),
                )
            )
        )
        for date, used_traffic in daily_query.all():
            timestamp = datetime(
                date.year, date.month, date.day, tzinfo=timezone.utc
            ).timestamp()
            usages[timestamp] += int(used_traffic)

    result = TrafficUsageSeries(usages=[], total=0)
    current = start.astimezone(timezone.utc).replace(
        minute=0, second=0, microsecond=0
    )

    while current <= end.replace(tzinfo=timezone.utc):
        usage = usages.get(current.timestamp()) or 0
        result.usages.append((int(current.timestamp()), usage))
        result.total += usage
        current += timedelta(hours=1)

    return result


def create_node(db: Session, node: NodeCreate):
    dbnode = Node(
        name=node.name,
        address=node.address,
        port=node.port,
        connection_backend=node.connection_backend,
    )

    db.add(dbnode)
    db.commit()
    db.refresh(dbnode)
    return dbnode


def remove_node(db: Session, dbnode: Node):
    db.delete(dbnode)
    db.commit()
    return dbnode


def update_node(db: Session, dbnode: Node, modify: NodeModify):
    if modify.name is not None:
        dbnode.name = modify.name

    if modify.address is not None:
        dbnode.address = modify.address

    if modify.port is not None:
        dbnode.port = modify.port

    if modify.status is NodeStatus.disabled:
        dbnode.status = modify.status
        dbnode.xray_version = None
        dbnode.message = None
    else:
        dbnode.status = NodeStatus.unhealthy

    if modify.usage_coefficient is not None:
        dbnode.usage_coefficient = modify.usage_coefficient

    if modify.connection_backend:
        dbnode.connection_backend = modify.connection_backend

    db.commit()
    db.refresh(dbnode)
    return dbnode


def update_node_status(
    db: Session,
    node_id: int,
    status: NodeStatus,
    message: str = None,
    version: str = None,
):
    db_node = db.query(Node).where(Node.id == node_id).first()
    db_node.status = status
    if message:
        db_node.message = message
    db_node.last_status_change = datetime.utcnow()
    db.commit()
