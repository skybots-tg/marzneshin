import secrets
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import List, Optional, Tuple, Union

from sqlalchemy import and_, update, func, cast, Date
from sqlalchemy.orm import Session

from app.db.models import Admin, Node, NodeUserUsage, Service, User
from app.db.models.proxy import NodeUserUsageDaily
from app.core.settings import settings
from app.models.system import TrafficUsageSeries
from app.models.user import (
    UserCreate,
    UserDataUsageResetStrategy,
    UserModify,
    UserStatus,
    UserExpireStrategy,
    UserNodeUsageSeries,
    UserUsageSeriesResponse,
)


def get_user(db: Session, username: str):
    return db.query(User).filter(User.username == username).first()


def get_user_by_id(db: Session, user_id: int):
    return db.query(User).filter(User.id == user_id).first()


UsersSortingOptions = Enum(
    "UsersSortingOptions",
    {
        "username": User.username.asc(),
        "used_traffic": User.used_traffic.asc(),
        "data_limit": User.data_limit.asc(),
        "expire": User.expire_date.asc(),
        "created_at": User.created_at.asc(),
        "-username": User.username.desc(),
        "-used_traffic": User.used_traffic.desc(),
        "-data_limit": User.data_limit.desc(),
        "-expire": User.expire_date.desc(),
        "-created_at": User.created_at.desc(),
    },
)


def get_users(
    db: Session,
    offset: Optional[int] = None,
    limit: Optional[int] = None,
    usernames: Optional[List[str]] = None,
    sort: Optional[List[UsersSortingOptions]] = None,
    admin: Optional[Admin] = None,
    reset_strategy: Optional[Union[UserDataUsageResetStrategy, list]] = None,
    expire_strategy: (
        UserExpireStrategy | list[UserExpireStrategy] | None
    ) = None,
    is_active: bool | None = None,
    activated: bool | None = None,
    expired: bool | None = None,
    data_limit_reached: bool | None = None,
    enabled: bool | None = None,
) -> Union[List[User], Tuple[List[User], int]]:
    query = db.query(User).filter(User.removed == False)

    if usernames:
        if len(usernames) == 1:
            query = query.filter(User.username.ilike(f"%{usernames[0]}%"))
        else:
            query = query.filter(User.username.in_(usernames))

    if reset_strategy:
        if isinstance(reset_strategy, list):
            query = query.filter(
                User.data_limit_reset_strategy.in_(reset_strategy)
            )
        else:
            query = query.filter(
                User.data_limit_reset_strategy == reset_strategy
            )

    if expire_strategy:
        if isinstance(expire_strategy, list):
            query = query.filter(User.expire_strategy.in_(expire_strategy))
        else:
            query = query.filter(User.expire_strategy == expire_strategy)

    if isinstance(is_active, bool):
        query = query.filter(User.is_active == is_active)

    if isinstance(activated, bool):
        query = query.filter(User.activated == activated)

    if isinstance(expired, bool):
        query = query.filter(User.expired == expired)

    if isinstance(data_limit_reached, bool):
        query = query.filter(User.data_limit_reached == data_limit_reached)

    if isinstance(enabled, bool):
        query = query.filter(User.enabled == enabled)

    if admin:
        query = query.filter(User.admin == admin)

    if sort:
        query = query.order_by(*(opt.value for opt in sort))

    if offset:
        query = query.offset(offset)

    if limit:
        query = query.limit(limit)

    return query.all()


def _make_aware(dt: datetime) -> datetime:
    """Ensure a datetime is timezone-aware (UTC)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _get_retention_cutoff() -> datetime:
    """Boundary between hourly (recent) and daily (old) data. Always aware."""
    return datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ) - timedelta(days=settings.tasks.usage_retention_days)


def get_user_total_usage(
    db: Session, user: User, start: datetime, end: datetime, per_day=False
):
    usages = defaultdict(int)
    cutoff = _get_retention_cutoff()
    start = _make_aware(start)
    end = _make_aware(end)

    # Hourly data (recent period)
    hourly_start = max(start, cutoff)
    if hourly_start < end:
        query = db.query(
            (
                cast(NodeUserUsage.created_at, Date).label("day")
                if per_day
                else NodeUserUsage.created_at
            ),
            func.sum(NodeUserUsage.used_traffic),
        ).filter(
            and_(
                NodeUserUsage.user_id == user.id,
                NodeUserUsage.created_at >= hourly_start,
                NodeUserUsage.created_at <= end,
            )
        )
        if per_day:
            query = query.group_by(cast(NodeUserUsage.created_at, Date))
        else:
            query = query.group_by(NodeUserUsage.created_at)

        for date, used_traffic in query:
            if per_day:
                timestamp = datetime(
                    date.year, date.month, date.day, tzinfo=timezone.utc
                ).timestamp()
            else:
                timestamp = date.replace(tzinfo=timezone.utc).timestamp()
            usages[timestamp] += int(used_traffic)

    # Daily data (older period)
    if start < cutoff:
        daily_end = min(end, cutoff - timedelta(seconds=1))
        daily_query = db.query(
            NodeUserUsageDaily.date,
            func.sum(NodeUserUsageDaily.used_traffic),
        ).filter(
            and_(
                NodeUserUsageDaily.user_id == user.id,
                NodeUserUsageDaily.date >= start.date(),
                NodeUserUsageDaily.date <= daily_end.date(),
            )
        ).group_by(NodeUserUsageDaily.date)

        for date, used_traffic in daily_query:
            timestamp = datetime(
                date.year, date.month, date.day, tzinfo=timezone.utc
            ).timestamp()
            usages[timestamp] += int(used_traffic)

    result = TrafficUsageSeries(usages=[])
    current = start.astimezone(timezone.utc).replace(
        minute=0, second=0, microsecond=0
    )
    if per_day:
        current = current.replace(hour=0)

    step = timedelta(days=1) if per_day else timedelta(hours=1)
    while current <= end.replace(tzinfo=timezone.utc):
        current_usage = usages.get(current.timestamp()) or 0
        result.usages.append((int(current.timestamp()), current_usage))
        result.total += current_usage
        current += step

    result.step = int(step.total_seconds())
    return result


def get_total_usages(
    db: Session, admin: Admin, start: datetime, end: datetime
) -> TrafficUsageSeries:
    usages = defaultdict(int)
    cutoff = _get_retention_cutoff()
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
                    NodeUserUsage.created_at >= hourly_start,
                    NodeUserUsage.created_at <= end,
                )
            )
        )
        if not admin.is_sudo:
            query = (
                query.filter(Admin.id == admin.id)
                .join(User, NodeUserUsage.user_id == User.id)
                .join(Admin, User.admin_id == Admin.id)
            )
        for created_at, used_traffic in query.all():
            timestamp = created_at.replace(tzinfo=timezone.utc).timestamp()
            usages[timestamp] += int(used_traffic)

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
                    NodeUserUsageDaily.date >= start.date(),
                    NodeUserUsageDaily.date <= daily_end.date(),
                )
            )
        )
        if not admin.is_sudo:
            daily_query = (
                daily_query.filter(Admin.id == admin.id)
                .join(User, NodeUserUsageDaily.user_id == User.id)
                .join(Admin, User.admin_id == Admin.id)
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


def get_user_usages(
    db: Session,
    db_user: User,
    start: datetime,
    end: datetime,
) -> UserUsageSeriesResponse:
    usages = defaultdict(lambda: defaultdict(int))
    cutoff = _get_retention_cutoff()
    start = _make_aware(start)
    end = _make_aware(end)

    # Hourly data
    hourly_start = max(start, cutoff)
    if hourly_start < end:
        cond = and_(
            NodeUserUsage.user_id == db_user.id,
            NodeUserUsage.created_at >= hourly_start,
            NodeUserUsage.created_at <= end,
        )
        for v in db.query(NodeUserUsage).filter(cond):
            timestamp = v.created_at.replace(tzinfo=timezone.utc).timestamp()
            usages[v.node_id][timestamp] += v.used_traffic

    # Daily data
    if start < cutoff:
        daily_end = min(end, cutoff - timedelta(seconds=1))
        daily_cond = and_(
            NodeUserUsageDaily.user_id == db_user.id,
            NodeUserUsageDaily.date >= start.date(),
            NodeUserUsageDaily.date <= daily_end.date(),
        )
        for v in db.query(NodeUserUsageDaily).filter(daily_cond):
            timestamp = datetime(
                v.date.year, v.date.month, v.date.day, tzinfo=timezone.utc
            ).timestamp()
            usages[v.node_id][timestamp] += v.used_traffic

    node_ids = list(usages.keys())
    nodes = db.query(Node).where(Node.id.in_(node_ids)) if node_ids else []
    node_id_names = {node.id: node.name for node in nodes}

    result = UserUsageSeriesResponse(
        username=db_user.username, node_usages=[], total=0
    )

    for node_id, rows in usages.items():
        if not node_id or node_id not in node_id_names:
            continue

        node_usages = UserNodeUsageSeries(
            node_id=node_id, node_name=node_id_names[node_id], usages=[]
        )
        current = start.astimezone(timezone.utc).replace(
            minute=0, second=0, microsecond=0
        )

        while current <= end.replace(tzinfo=timezone.utc):
            usage = rows.get(current.timestamp()) or 0
            node_usages.usages.append((int(current.timestamp()), usage))
            current += timedelta(hours=1)
            result.total += usage
        result.node_usages.append(node_usages)

    return result


def get_users_count(
    db: Session,
    admin: Admin | None = None,
    enabled: bool | None = None,
    online: bool | None = None,
    expire_strategy: UserExpireStrategy | None = None,
    is_active: bool | None = None,
    expired: bool | None = None,
    data_limit_reached: bool | None = None,
):
    query = db.query(User.id).filter(User.removed == False)
    if admin:
        query = query.filter(User.admin_id == admin.id)
    if is_active:
        query = query.filter(User.is_active == is_active)
    if expired:
        query = query.filter(User.expired == expired)
    if data_limit_reached:
        query = query.filter(User.data_limit_reached == data_limit_reached)
    if enabled:
        query = query.filter(User.enabled == enabled)
    if online is True:
        query = query.filter(
            User.online_at > (datetime.utcnow() - timedelta(seconds=30))
        )
    elif online is False:
        query = query.filter(
            User.online_at < (datetime.utcnow() - timedelta(seconds=30))
        )
    if expire_strategy:
        query = query.filter(User.expire_strategy == expire_strategy)

    return query.count()


def create_user(
    db: Session,
    user: UserCreate,
    admin: Admin = None,
    allowed_services: list | None = None,
):
    service_ids = (
        [sid for sid in user.service_ids if sid in allowed_services]
        if allowed_services is not None
        else user.service_ids
    )
    dbuser = User(
        username=user.username,
        key=user.key,
        expire_strategy=user.expire_strategy,
        expire_date=user.expire_date,
        usage_duration=user.usage_duration,
        activation_deadline=user.activation_deadline,
        services=db.query(Service)
        .filter(Service.id.in_(service_ids))
        .all(),
        data_limit=(user.data_limit or None),
        device_limit=user.device_limit,
        admin=admin,
        data_limit_reset_strategy=user.data_limit_reset_strategy,
        note=user.note,
    )
    db.add(dbuser)
    db.commit()
    db.refresh(dbuser)
    return dbuser


def remove_user(db: Session, dbuser: User):
    dbuser.username = None
    dbuser.removed = True
    dbuser.activated = False
    db.commit()


def update_user(
    db: Session,
    dbuser: User,
    modify: UserModify,
    allowed_services: list | None = None,
):
    if modify.data_limit is not None:
        dbuser.data_limit = modify.data_limit or None

    if modify.expire_strategy is not None:
        dbuser.expire_strategy = modify.expire_strategy or None

        if modify.expire_strategy == UserExpireStrategy.FIXED_DATE:
            dbuser.usage_duration = None
            dbuser.activation_deadline = None
        elif modify.expire_strategy == UserExpireStrategy.START_ON_FIRST_USE:
            dbuser.expire_date = None
        elif modify.expire_strategy == UserExpireStrategy.NEVER:
            dbuser.expire_date = None
            dbuser.usage_duration = None
            dbuser.activation_deadline = None

    if modify.expire_date is not None:
        dbuser.expire_date = modify.expire_date or None

    if modify.note is not None:
        dbuser.note = modify.note or None

    if modify.data_limit_reset_strategy is not None:
        dbuser.data_limit_reset_strategy = modify.data_limit_reset_strategy

    if modify.activation_deadline is not None:
        dbuser.activation_deadline = modify.activation_deadline

    if modify.usage_duration is not None:
        dbuser.usage_duration = modify.usage_duration

    # device_limit: true PATCH semantics — distinguish "field omitted" from
    # "field set to null". Cannot use ``is not None`` like data_limit does,
    # because here ``0`` and ``None`` are BOTH valid values with distinct
    # meanings (``0`` = block all new devices, ``None`` = unlimited).
    if "device_limit" in modify.model_fields_set:
        dbuser.device_limit = modify.device_limit

    if modify.service_ids is not None:
        if allowed_services is not None:
            service_ids = [
                sid for sid in modify.service_ids if sid in allowed_services
            ]
        else:
            service_ids = modify.service_ids

        dbuser.services = (
            db.query(Service).filter(Service.id.in_(service_ids)).all()
        )
    dbuser.edit_at = datetime.utcnow()

    db.commit()
    db.refresh(dbuser)
    return dbuser


def reset_user_data_usage(db: Session, dbuser: User):
    dbuser.traffic_reset_at = datetime.utcnow()

    dbuser.used_traffic = 0

    db.add(dbuser)

    db.commit()
    db.refresh(dbuser)
    return dbuser


def revoke_user_sub(db: Session, dbuser: User):
    dbuser.key = secrets.token_hex(16)
    dbuser.sub_revoked_at = datetime.utcnow()
    db.commit()
    db.refresh(dbuser)
    return dbuser


def update_user_sub(db: Session, dbuser: User, user_agent: str):
    """Update subscription metadata.

    Uses the session's own connection instead of engine.begin() to avoid
    checking out a *second* pool connection per subscription request.
    """
    db.execute(
        update(User)
        .where(User.id == dbuser.id)
        .values(
            sub_updated_at=datetime.utcnow(),
            sub_last_user_agent=user_agent,
        )
    )
    db.commit()


def reset_all_users_data_usage(db: Session, admin: Optional[Admin] = None):
    query = db.query(User)

    if admin:
        query = query.filter(User.admin == admin)

    for db_user in query.all():
        db_user.used_traffic = 0

    db.commit()


def update_user_status(db: Session, dbuser: User, status: UserStatus):
    dbuser.status = status
    db.commit()
    db.refresh(dbuser)
    return dbuser


def set_owner(db: Session, dbuser: User, admin: Admin):
    dbuser.admin = admin
    db.commit()
    db.refresh(dbuser)
    return dbuser
