import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional, Union

from sqlalchemy import and_, func
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

ProgressCallback = Optional[Callable[[dict], None]]

from app.db.models import Node, NodeUsage, NodeUserUsage
from app.db.models.proxy import NodeUsageDaily, NodeUserUsageDaily
from app.core.settings import settings
from app.models.node import NodeCreate, NodeModify, NodeStatus
from app.models.system import TrafficUsageSeries

logger = logging.getLogger(__name__)

_NODE_USAGE_DELETE_BATCH = 2000


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


def _make_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def get_node_usage(
    db: Session, start: datetime, end: datetime, node: Node
) -> TrafficUsageSeries:
    usages = defaultdict(int)
    cutoff = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ) - timedelta(days=settings.tasks.usage_retention_days)
    start = _make_aware(start)
    end = _make_aware(end)

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


def _emit(on_progress: ProgressCallback, **event) -> None:
    if on_progress is None:
        return
    try:
        on_progress(event)
    except Exception:
        logger.debug("remove_node progress callback failed", exc_info=True)


def _batched_delete_usage(
    db: Session,
    model,
    node_id: int,
    on_progress: ProgressCallback = None,
) -> int:
    """Удаляет строки usage-таблицы, относящиеся к ноде, пакетами с коммитами.

    У таблиц *_usages(_daily) нет ON DELETE CASCADE на уровне БД, а ORM-cascade
    выставлен только на save-update/merge. Один большой DELETE на активной ноде
    выбивает `Lost connection to MySQL server during query (timed out)`
    (см. read_timeout / max_execution_time в app/db/base.py), поэтому удаляем
    чанками по `_NODE_USAGE_DELETE_BATCH` строк и коммитим между ними.

    Если передан `on_progress`, для каждой таблицы генерируются события
    step_start / progress / step_done, чтобы клиент мог показывать прогресс
    в реальном времени (см. SSE-эндпоинт удаления ноды).
    """
    table = model.__tablename__

    total = (
        db.query(func.count(model.id))
        .filter(model.node_id == node_id)
        .scalar()
        or 0
    )
    _emit(on_progress, kind="step_start", table=table, total=total)

    done = 0
    while True:
        ids = [
            row[0]
            for row in db.query(model.id)
            .filter(model.node_id == node_id)
            .limit(_NODE_USAGE_DELETE_BATCH)
            .all()
        ]
        if not ids:
            break
        db.query(model).filter(model.id.in_(ids)).delete(
            synchronize_session=False
        )
        db.commit()
        done += len(ids)
        _emit(
            on_progress,
            kind="progress",
            table=table,
            done=done,
            total=max(total, done),
        )

    if done:
        logger.info(
            "Deleted %d rows from %s for node_id=%s",
            done,
            table,
            node_id,
        )
    _emit(
        on_progress,
        kind="step_done",
        table=table,
        done=done,
        total=max(total, done),
    )
    return done


def remove_node(
    db: Session,
    dbnode: Node,
    on_progress: ProgressCallback = None,
):
    node_id = dbnode.id

    # Порядок: сначала daily-агрегаты (обычно компактные), потом hourly-таблицы,
    # которые могут содержать миллионы строк на долгоживущей ноде.
    for model in (NodeUserUsageDaily, NodeUsageDaily, NodeUserUsage, NodeUsage):
        try:
            _batched_delete_usage(db, model, node_id, on_progress=on_progress)
        except OperationalError:
            db.rollback()
            _emit(
                on_progress,
                kind="step_error",
                table=model.__tablename__,
            )
            raise

    _emit(on_progress, kind="step_start", table="nodes", total=1)
    db.delete(dbnode)
    db.commit()
    _emit(on_progress, kind="step_done", table="nodes", done=1, total=1)
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
    if db_node is None:
        return
    # Operator-disabled nodes must stay disabled. The background monitor
    # may still emit healthy/unhealthy transitions for in-flight RPCs
    # while the connection is being torn down; ignore those so we don't
    # silently re-enable a node the operator just turned off.
    if db_node.status == NodeStatus.disabled:
        return
    db_node.status = status
    if message:
        db_node.message = message
    db_node.last_status_change = datetime.utcnow()
    db.commit()
